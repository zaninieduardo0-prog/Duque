from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from core.events import EventType
from core.task_engine import StepResult, TaskEngine
from core.tasks import Task, TaskManager, TaskStatus

from .scheduler import ScheduledJob, Scheduler


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
        self.scheduler.executor = self.run

    def _emit(self, event: EventType, **data: Any) -> None:
        if self.event_sink:
            self.event_sink(event, **data)

    def run(self, job: ScheduledJob) -> ScheduledExecution:
        kind = str(job.metadata.get("kind", "reminder"))
        if kind == "reminder":
            return self._run_reminder(job)
        if kind != "task":
            error = f"Tipo de job não suportado: {kind}"
            self._emit(EventType.ERROR, source="scheduler", job_id=job.id, error=error)
            return ScheduledExecution(job.id, kind, error=error)

        task: Task | None = None
        try:
            task = self._resolve_task(job)
            steps = self._steps(job)
            if not steps:
                raise ValueError("Tarefa agendada não possui etapas executáveis")
            results = self.task_engine.run(task, steps)
            if self.task_engine.succeeded(results):
                return ScheduledExecution(job.id, kind, task.id, results=results)
            failed = next((item for item in reversed(results) if not item.result.success), None)
            return ScheduledExecution(job.id, kind, task.id, results=results, error=failed.result.error if failed else "Falha desconhecida")
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            task_id = task.id if task else (str(job.metadata.get("task_id")) if job.metadata.get("task_id") else None)
            if task is not None and task.status == TaskStatus.RUNNING:
                self.tasks.fail(task.id, error)
            self._emit(EventType.TASK_FAILED, task_id=task_id, job_id=job.id, error=error)
            return ScheduledExecution(job.id, kind, task_id, error=error)

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
