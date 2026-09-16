from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable
from uuid import uuid4


@dataclass(slots=True)
class ScheduledJob:
    description: str
    run_at: float
    callback: Callable[[], Any] | None = None
    id: str = field(default_factory=lambda: uuid4().hex)
    repeat_seconds: float | None = None
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


class Scheduler:
    """Agendador local em memória; persistência dos jobs entra no storage operacional."""

    def __init__(self, poll_interval: float = 0.5) -> None:
        self.poll_interval = max(0.1, poll_interval)
        self._jobs: dict[str, ScheduledJob] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def add(self, description: str, run_at: float | datetime, callback: Callable[[], Any] | None = None, *, repeat_seconds: float | None = None, **metadata: Any) -> ScheduledJob:
        timestamp = run_at.timestamp() if isinstance(run_at, datetime) else float(run_at)
        job = ScheduledJob(description, timestamp, callback, repeat_seconds=max(0.1, repeat_seconds) if repeat_seconds else None, metadata=metadata)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def add_after(self, description: str, seconds: float, callback: Callable[[], Any] | None = None, *, repeat_seconds: float | None = None, **metadata: Any) -> ScheduledJob:
        return self.add(description, time.time() + max(0, seconds), callback, repeat_seconds=repeat_seconds, **metadata)

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            job.enabled = False
            return True

    def list(self, include_disabled: bool = False) -> list[ScheduledJob]:
        with self._lock:
            jobs = list(self._jobs.values())
        if not include_disabled:
            jobs = [job for job in jobs if job.enabled]
        return sorted(jobs, key=lambda job: job.run_at)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="DuqueScheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop.wait(self.poll_interval):
            now = time.time()
            due: list[ScheduledJob] = []
            with self._lock:
                for job in self._jobs.values():
                    if job.enabled and job.run_at <= now:
                        due.append(job)
            for job in due:
                self._execute(job)

    def _execute(self, job: ScheduledJob) -> None:
        try:
            if job.callback:
                job.callback()
        finally:
            with self._lock:
                if job.repeat_seconds and job.enabled:
                    job.run_at = time.time() + job.repeat_seconds
                else:
                    job.enabled = False
