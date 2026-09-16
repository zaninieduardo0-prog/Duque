from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from .scheduler import ScheduledJob, Scheduler


@dataclass(slots=True, frozen=True)
class Reminder:
    job_id: str
    description: str
    run_at: float


class AutomationTasks:
    """API de alto nível para lembretes e tarefas agendadas."""

    def __init__(self, scheduler: Scheduler | None = None) -> None:
        self.scheduler = scheduler or Scheduler()

    def remind_at(self, description: str, when: datetime, callback: Callable[[], Any] | None = None) -> Reminder:
        job = self.scheduler.add(description, when, callback, kind="reminder")
        return self._reminder(job)

    def remind_after(self, description: str, seconds: float, callback: Callable[[], Any] | None = None) -> Reminder:
        job = self.scheduler.add_after(description, seconds, callback, kind="reminder")
        return self._reminder(job)

    def schedule_task_at(self, description: str, when: datetime, *, task_id: str | None = None, steps: list[dict[str, Any]] | None = None, repeat_seconds: float | None = None, **metadata: Any) -> Reminder:
        job = self.scheduler.add_task(description, when, task_id=task_id, steps=steps, repeat_seconds=repeat_seconds, **metadata)
        return self._reminder(job)

    def schedule_task_after(self, description: str, seconds: float, *, task_id: str | None = None, steps: list[dict[str, Any]] | None = None, repeat_seconds: float | None = None, **metadata: Any) -> Reminder:
        job = self.scheduler.add_task_after(description, seconds, task_id=task_id, steps=steps, repeat_seconds=repeat_seconds, **metadata)
        return self._reminder(job)

    def cancel(self, job_id: str) -> bool:
        return self.scheduler.cancel(job_id)

    @staticmethod
    def _reminder(job: ScheduledJob) -> Reminder:
        return Reminder(job.id, job.description, job.run_at)
