from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from threading import RLock
from time import time
from uuid import uuid4
from typing import Any

from memory.database import MemoryDatabase


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class Task:
    description: str
    id: str = field(default_factory=lambda: uuid4().hex)
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: str | None = None
    created_at: float = field(default_factory=time)
    started_at: float | None = None
    finished_at: float | None = None
    attempts: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


# Uma confirmação ("sim"/"confirmo") só vale para o pedido que o Du acabou de
# fazer. Depois de um reinício, uma pendência antiga seria confirmada por um
# "sim" dito para outra coisa e dispararia uma ação de alto risco.
CONFIRMATION_TTL = 10 * 60


class TaskManager:
    """Gerencia tarefas em memória e mantém seu estado no SQLite."""

    def __init__(self, database: MemoryDatabase | None = None, *, clock: Any = time) -> None:
        self.database = database or MemoryDatabase()
        self._clock = clock
        # Flask (várias threads), agenda e Forja usam o mesmo gerenciador.
        self._lock = RLock()
        self._tasks: dict[str, Task] = {}
        self._load()

    def _load(self) -> None:
        for row in self.database.load_tasks():
            try:
                result = json.loads(row["result"]) if row["result"] is not None else None
                metadata = json.loads(row["metadata"] or "{}")
                task = Task(
                    description=row["description"], id=row["id"],
                    status=TaskStatus(row["status"]), result=result,
                    error=row["error"], created_at=row["created_at"],
                    started_at=row["started_at"], finished_at=row["finished_at"],
                    attempts=row["attempts"], metadata=metadata,
                )
                if task.status == TaskStatus.RUNNING:
                    task.status = TaskStatus.PENDING
                    task.error = "Processo anterior foi encerrado antes da conclusão"
                    self.database.upsert_task(task)
                elif task.status == TaskStatus.AWAITING_CONFIRMATION and self._confirmation_expired(task):
                    task.status = TaskStatus.CANCELLED
                    task.error = "Confirmação expirou (o TELEX reiniciou ou ninguém respondeu)"
                    task.finished_at = self._clock()
                    task.metadata.pop("confirmation_pending", None)
                    task.metadata.pop("confirmation_prompt", None)
                    self.database.upsert_task(task)
                self._tasks[task.id] = task
            except (KeyError, ValueError, TypeError, json.JSONDecodeError):
                continue

    def _confirmation_expired(self, task: Task) -> bool:
        # Tarefa agendada nunca fica esperando um "sim" (ninguém pediu na hora).
        if task.metadata.get("source") in {"scheduler", "scheduled"} or task.metadata.get("scheduled"):
            return True
        moment = task.started_at or task.created_at
        return self._clock() - float(moment or 0) > CONFIRMATION_TTL

    def _save(self, task: Task) -> None:
        self.database.upsert_task(task)

    def create(self, description: str, **metadata: Any) -> Task:
        task = Task(description=description, metadata=metadata)
        with self._lock:
            self._tasks[task.id] = task
            self._save(task)
        return task

    def get(self, task_id: str) -> Task | None:
        with self._lock:
            return self._tasks.get(task_id)

    def start(self, task_id: str) -> Task:
        with self._lock:
            task = self._tasks[task_id]
            if task.status in {TaskStatus.COMPLETED, TaskStatus.CANCELLED}:
                raise RuntimeError(f"Tarefa {task_id} não pode ser iniciada em estado {task.status.value}")
            task.status = TaskStatus.RUNNING
            task.started_at = time()
            task.finished_at = None
            task.error = None
            task.attempts += 1
            self._save(task)
            return task

    def await_confirmation(self, task_id: str, prompt: str) -> Task:
        with self._lock:
            task = self._tasks[task_id]
            if task.status != TaskStatus.RUNNING:
                raise RuntimeError(f"Tarefa {task_id} não pode aguardar confirmação em estado {task.status.value}")
            task.status = TaskStatus.AWAITING_CONFIRMATION
            task.error = prompt
            task.finished_at = None
            task.metadata["confirmation_pending"] = True
            task.metadata["confirmation_prompt"] = prompt
            self._save(task)
            return task

    def set_confirmation_context(self, task_id: str, **metadata: Any) -> Task:
        """Persiste os dados necessários para retomar uma confirmação após reinício."""
        with self._lock:
            task = self._tasks[task_id]
            if task.status != TaskStatus.AWAITING_CONFIRMATION:
                raise RuntimeError(
                    f"Tarefa {task_id} não está aguardando confirmação em estado {task.status.value}"
                )
            task.metadata.update(metadata)
            self._save(task)
            return task

    def complete(self, task_id: str, result: Any = None) -> Task:
        with self._lock:
            task = self._tasks[task_id]
            if task.status != TaskStatus.RUNNING:
                raise RuntimeError(f"Tarefa {task_id} não pode ser concluída em estado {task.status.value}")
            task.status = TaskStatus.COMPLETED
            task.result = result
            task.error = None
            task.finished_at = time()
            task.metadata.pop("confirmation_pending", None)
            task.metadata.pop("confirmation_prompt", None)
            self._save(task)
            return task

    def fail(self, task_id: str, error: str) -> Task:
        with self._lock:
            task = self._tasks[task_id]
            if task.status != TaskStatus.RUNNING:
                raise RuntimeError(f"Tarefa {task_id} não pode falhar em estado {task.status.value}")
            task.status = TaskStatus.FAILED
            task.error = error
            task.finished_at = time()
            task.metadata.pop("confirmation_pending", None)
            task.metadata.pop("confirmation_prompt", None)
            self._save(task)
            return task

    def cancel(self, task_id: str) -> Task:
        with self._lock:
            task = self._tasks[task_id]
            if task.status not in {TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.AWAITING_CONFIRMATION, TaskStatus.FAILED}:
                raise RuntimeError(f"Tarefa {task_id} não pode ser cancelada em estado {task.status.value}")
            task.status = TaskStatus.CANCELLED
            task.finished_at = time()
            task.metadata.pop("confirmation_pending", None)
            task.metadata.pop("confirmation_prompt", None)
            self._save(task)
            return task

    def list(self, status: TaskStatus | None = None) -> list[Task]:
        with self._lock:
            tasks = list(self._tasks.values())
        if status is not None:
            tasks = [task for task in tasks if task.status == status]
        return sorted(tasks, key=lambda task: task.created_at)
