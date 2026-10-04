from __future__ import annotations

import logging
from contextlib import nullcontext
from dataclasses import dataclass, replace
from typing import Any, Callable

from core.events import EventType
from core.task_engine import StepResult, TaskEngine
from core.tasks import Task, TaskManager, TaskStatus

from .scheduler import ScheduledJob, Scheduler

LOGGER = logging.getLogger(__name__)

# Tarefa agendada (que abre apps, clica, digita) atrasada mais do que isto não é
# executada: com o TELEX desligado no horário, rodar tudo no boot abria janelas
# fora de hora a cada reinício. O Du recebe um aviso no lugar.
MISSED_TASK_GRACE = 15 * 60


@dataclass(slots=True)
class ScheduledExecution:
    job_id: str
    kind: str
    task_id: str | None = None
    results: list[StepResult] | None = None
    error: str | None = None


class ScheduledTaskRunner:
    """Transforma jobs persistentes do Scheduler em execuções reais do TaskEngine."""

    def __init__(self, scheduler: Scheduler, task_engine: TaskEngine, tasks: TaskManager | None = None, event_sink: Callable[..., Any] | None = None, reminder_handler: Callable[[ScheduledJob], Any] | None = None) -> None:
        self.scheduler = scheduler
        self.task_engine = task_engine
        self.tasks = tasks or task_engine.tasks
        self.event_sink = event_sink
        self.reminder_handler = reminder_handler
        # Pausa de emergência: lembretes e tarefas agendadas esperam a retomada.
        self.pause: Any | None = None
        # Lock do AgentLoop.handle: uma tarefa agendada nunca roda ferramentas ao
        # mesmo tempo que um pedido do Du (ações cruzadas na mesma tela).
        self.lock: Any | None = None
        self.scheduler.executor = self.run

    def _emit(self, event: EventType, **data: Any) -> None:
        if self.event_sink:
            self.event_sink(event, **data)

    def run(self, job: ScheduledJob) -> ScheduledExecution:
        if self.pause is not None:
            self.pause.checkpoint(f"agenda:{job.id}", {"trabalho": f"Agenda: {job.description}"[:90], "etapa": "aguardando a hora"})
        kind = str(job.metadata.get("kind", "reminder"))
        if kind == "reminder":
            return self._run_reminder(job)
        if kind != "task":
            error = f"Tipo de job não suportado: {kind}"
            self._emit(EventType.ERROR, source="scheduler", job_id=job.id, error=error)
            return ScheduledExecution(job.id, kind, error=error)

        if job.late_seconds > MISSED_TASK_GRACE:
            return self._skip_missed(job)

        task: Task | None = None
        try:
            task = self._resolve_task(job)
            steps = self._steps(job)
            if not steps:
                raise ValueError("Tarefa agendada não possui etapas executáveis")
            with self.lock if self.lock is not None else nullcontext():
                results = self.task_engine.run(task, steps)
            if self.task_engine.succeeded(results):
                return ScheduledExecution(job.id, kind, task.id, results=results)
            failed = next((item for item in reversed(results) if not item.result.success), None)
            error = failed.result.error if failed else "Falha desconhecida"
            if task.status == TaskStatus.AWAITING_CONFIRMATION:
                # Ninguém está ali para dizer "sim": antes a tarefa ficava esperando
                # para sempre e um "sim" dito depois para outra coisa a disparava.
                self.tasks.cancel(task.id)
                error = f"Tarefa agendada não executada: {error} (ações de risco não rodam sozinhas)"
                self._emit(EventType.TASK_FAILED, task_id=task.id, job_id=job.id, error=error)
            return ScheduledExecution(job.id, kind, task.id, results=results, error=error)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            task_id = task.id if task else (str(job.metadata.get("task_id")) if job.metadata.get("task_id") else None)
            if task is not None and task.status == TaskStatus.RUNNING:
                self.tasks.fail(task.id, error)
            self._emit(EventType.TASK_FAILED, task_id=task_id, job_id=job.id, error=error)
            return ScheduledExecution(job.id, kind, task_id, error=error)

    def _skip_missed(self, job: ScheduledJob) -> ScheduledExecution:
        scheduled = job.scheduled_for if job.scheduled_for is not None else job.run_at
        error = "Tarefa agendada perdida (o TELEX estava desligado no horário); não executei fora de hora"
        LOGGER.warning("%s: %s", error, job.description)
        self._emit(EventType.ERROR, source="scheduler", job_id=job.id, error=error)
        if self.reminder_handler:
            # Avisa o Du ("Era para HH:MM; o Duque estava desligado") em vez de agir.
            notice = replace(job, run_at=scheduled, metadata={"kind": "reminder", "missed_task": True})
            try:
                self.reminder_handler(notice)
            except Exception:
                LOGGER.exception("Falha ao avisar a tarefa perdida: %s", job.description)
        return ScheduledExecution(job.id, "task", str(job.metadata.get("task_id") or "") or None, error=error)

    def _resolve_task(self, job: ScheduledJob) -> Task:
        task_id = job.metadata.get("task_id")
        task = self.tasks.get(str(task_id)) if task_id else None
        if task is None or task.status in {TaskStatus.COMPLETED, TaskStatus.CANCELLED}:
            task = self.tasks.create(job.description, scheduled_job_id=job.id, source="scheduler")
            job.metadata["task_id"] = task.id
            self.scheduler._save(job)
        return task

    @staticmethod
    def _steps(job: ScheduledJob) -> list[tuple[str, dict[str, Any]]]:
        raw_steps = job.metadata.get("steps") or []
        if not isinstance(raw_steps, list):
            raise ValueError("steps deve ser uma lista")
        steps: list[tuple[str, dict[str, Any]]] = []
        for item in raw_steps:
            if not isinstance(item, dict):
                raise ValueError("Cada etapa deve ser um objeto")
            tool = item.get("tool")
            arguments = item.get("arguments") or {}
            if not isinstance(tool, str) or not tool.strip():
                raise ValueError("Cada etapa precisa de uma ferramenta")
            if not isinstance(arguments, dict):
                raise ValueError("arguments deve ser um objeto")
            steps.append((tool, arguments))
        return steps

    def _run_reminder(self, job: ScheduledJob) -> ScheduledExecution:
        try:
            if self.reminder_handler:
                self.reminder_handler(job)
            self._emit(EventType.MEMORY_UPDATED, kind="reminder_due", job_id=job.id, description=job.description)
            return ScheduledExecution(job.id, "reminder")
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            self._emit(EventType.ERROR, source="scheduler", job_id=job.id, error=error)
            return ScheduledExecution(job.id, "reminder", error=error)

    def start(self) -> None:
        self.scheduler.start()

    def stop(self) -> None:
        self.scheduler.stop()
