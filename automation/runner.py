from __future__ import annotations

import threading
from contextlib import nullcontext
from typing import Any, Callable

from core.events import EventType
from core.task_engine import TaskEngine
from core.tasks import Task, TaskManager, TaskStatus

from .scheduler import ScheduledJob, Scheduler


class ScheduledTaskRunner:
    """Transforma jobs persistentes do Scheduler em execuções reais do TaskEngine."""

    def __init__(
        self,
        scheduler: Scheduler,
        task_engine: TaskEngine,
        tasks: TaskManager | None = None,
        event_sink: Callable[..., Any] | None = None,
        lock: threading.RLock | None = None,
    ) -> None:
        self.scheduler = scheduler
        self.task_engine = task_engine
        self.tasks = tasks or task_engine.tasks
        self.event_sink = event_sink
        # O mesmo lock do AgentLoop: um job agendado nunca age na tela ao mesmo
        # tempo que um pedido do usuário.
        self.lock = lock
        self.scheduler.executor = self.run

    def _emit(self, event: EventType, **data: Any) -> None:
        if self.event_sink:
            self.event_sink(event, **data)

    def run(self, job: ScheduledJob) -> None:
        kind = str(job.metadata.get("kind", "reminder"))
        if kind == "reminder":
            self._emit(EventType.MEMORY_UPDATED, kind="reminder_due", job_id=job.id, description=job.description)
            return
        if kind != "task":
            self._emit(EventType.ERROR, source="scheduler", job_id=job.id, error=f"Tipo de job não suportado: {kind}")
            return
        with self.lock or nullcontext():
            self._run_task(job)

    def _run_task(self, job: ScheduledJob) -> None:
        task: Task | None = None
        try:
            task = self._resolve_task(job)
            steps = self._steps(job)
            if not steps:
                raise ValueError("Tarefa agendada não possui etapas executáveis")
            results = self.task_engine.run(task, steps)
            failed = next((item for item in reversed(results) if not item.result.success), None)
            if failed and failed.result.confirmation_required:
                # Ninguém está presente para confirmar; não deixa a tarefa presa.
                error = f"A ação '{failed.tool}' exige confirmação e não pode rodar agendada"
                self.tasks.cancel(task.id)
                self._emit(EventType.TASK_FAILED, task_id=task.id, job_id=job.id, error=error)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            if task is not None and task.status == TaskStatus.RUNNING:
                self.tasks.fail(task.id, error)
            self._emit(EventType.TASK_FAILED, task_id=task.id if task else None, job_id=job.id, error=error)

    def _resolve_task(self, job: ScheduledJob) -> Task:
        task_id = job.metadata.get("task_id")
        task = self.tasks.get(str(task_id)) if task_id else None
        if task is None or task.status in {TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.FAILED}:
            task = self.tasks.create(job.description, scheduled_job_id=job.id, source="scheduler")
            self.scheduler.update_metadata(job.id, task_id=task.id)
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

    def start(self) -> None:
        self.scheduler.start()
