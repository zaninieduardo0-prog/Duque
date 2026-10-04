from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable
from uuid import uuid4

from memory.database import MemoryDatabase


LOGGER = logging.getLogger(__name__)

# Repetição mínima: um "a cada 0,1 s" vindo do modelo abria janelas sem parar.
MIN_REPEAT_SECONDS = 60.0


@dataclass(slots=True)
class ScheduledJob:
    description: str
    run_at: float
    callback: Callable[[], Any] | None = None
    id: str = field(default_factory=lambda: uuid4().hex)
    repeat_seconds: float | None = None
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    last_run_at: float | None = None
    run_count: int = 0
    # Preenchidos a cada disparo (não persistem): horário que estava marcado e o atraso.
    scheduled_for: float | None = None
    late_seconds: float = 0.0


class Scheduler:
    """Agendador persistente; jobs sobrevivem ao restart e carregam uma intenção serializável."""

    def __init__(self, database: MemoryDatabase | None = None, poll_interval: float = 0.5, executor: Callable[[ScheduledJob], Any] | None = None, *, startup_delay: float = 3.0) -> None:
        self.database = database or MemoryDatabase()
        self.poll_interval = max(0.1, poll_interval)
        # Os atrasados do boot só rodam depois que o servidor/HUD terminaram de subir.
        self.startup_delay = max(0.0, startup_delay)
        self.executor = executor
        self._jobs: dict[str, ScheduledJob] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._load()

    def _load(self) -> None:
        for row in self.database.load_jobs(enabled_only=False):
            try:
                metadata = json.loads(row["metadata"] or "{}")
                self._jobs[row["id"]] = ScheduledJob(
                    description=row["description"], id=row["id"], run_at=row["run_at"],
                    repeat_seconds=max(MIN_REPEAT_SECONDS, float(row["repeat_seconds"])) if row["repeat_seconds"] else None,
                    enabled=bool(row["enabled"]),
                    metadata=metadata, created_at=row["created_at"],
                    last_run_at=row["last_run_at"], run_count=row["run_count"],
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue

    def add(self, description: str, run_at: float | datetime, callback: Callable[[], Any] | None = None, *, repeat_seconds: float | None = None, **metadata: Any) -> ScheduledJob:
        timestamp = run_at.timestamp() if isinstance(run_at, datetime) else float(run_at)
        repeat = max(MIN_REPEAT_SECONDS, float(repeat_seconds)) if repeat_seconds else None
        job = ScheduledJob(description, timestamp, callback, repeat_seconds=repeat, metadata=metadata)
        with self._lock:
            self._jobs[job.id] = job
            self._save(job)
        return job

    def add_task(self, description: str, run_at: float | datetime, *, task_id: str | None = None, steps: list[dict[str, Any]] | None = None, repeat_seconds: float | None = None, **metadata: Any) -> ScheduledJob:
        """Cria um job totalmente serializável; não depende de callback para sobreviver ao restart."""
        payload = dict(metadata)
        payload["kind"] = "task"
        payload["task_id"] = task_id
        payload["steps"] = steps or []
        return self.add(description, run_at, repeat_seconds=repeat_seconds, **payload)

    def add_after(self, description: str, seconds: float, callback: Callable[[], Any] | None = None, *, repeat_seconds: float | None = None, **metadata: Any) -> ScheduledJob:
        return self.add(description, time.time() + max(0, seconds), callback, repeat_seconds=repeat_seconds, **metadata)

    def add_task_after(self, description: str, seconds: float, *, task_id: str | None = None, steps: list[dict[str, Any]] | None = None, repeat_seconds: float | None = None, **metadata: Any) -> ScheduledJob:
        return self.add_task(description, time.time() + max(0, seconds), task_id=task_id, steps=steps, repeat_seconds=repeat_seconds, **metadata)

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            job.enabled = False
            self._save(job)
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
        # Antes os jobs atrasados rodavam aqui, de forma síncrona, ainda dentro do
        # import do servidor (antes dos assinantes de eventos existirem).
        self._thread = threading.Thread(target=self._run, name="DuqueScheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None

    def run_due(self) -> int:
        now = time.time()
        with self._lock:
            due = [job for job in self._jobs.values() if job.enabled and job.run_at <= now]
        for job in due:
            self._execute(job)
        return len(due)

    def _run(self) -> None:
        if self._stop.wait(self.startup_delay):
            return
        while True:
            try:
                self.run_due()
            except Exception:
                # Um erro (ex.: banco ocupado) não pode matar a agenda para sempre.
                LOGGER.exception("Falha no ciclo da agenda")
            if self._stop.wait(self.poll_interval):
                return

    def _execute(self, job: ScheduledJob) -> None:
        with self._lock:
            if not job.enabled or job.run_at > time.time():
                return
            now = time.time()
            job.scheduled_for = job.run_at
            job.late_seconds = max(0.0, now - job.run_at)
            job.last_run_at = now
            job.run_count += 1
            if job.repeat_seconds:
                # Próximo horário na grade original (sem deriva): um job perdido com o
                # TELEX desligado dispara uma vez só, não uma vez por intervalo perdido.
                missed = int((now - job.run_at) // job.repeat_seconds) + 1
                job.run_at = job.run_at + missed * job.repeat_seconds
            else:
                job.enabled = False
            self._save(job)

        try:
            if self.executor:
                self.executor(job)
            elif job.callback:
                job.callback()
        except Exception:
            LOGGER.exception("Falha ao executar tarefa agendada: %s", job.description)

    def _save(self, job: ScheduledJob) -> None:
        self.database.upsert_job(job, job.created_at, job.last_run_at, job.run_count)
