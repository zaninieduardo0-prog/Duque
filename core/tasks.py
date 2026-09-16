from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from time import time
from uuid import uuid4
from typing import Any

from memory.database import MemoryDatabase


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
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


class TaskManager:
    """Gerencia tarefas em memória e mantém seu estado no SQLite."""

    def __init__(self, database: MemoryDatabase | None = None) -> None:
        self.database = database or MemoryDatabase()
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
                # Um processo interrompido não deve deixar uma tarefa presa em RUNNING.
                if task.status == TaskStatus.RUNNING:
                    task.status = TaskStatus.PENDING
                    task.error = "Processo anterior foi encerrado antes da conclusão"
                self._tasks[task.id] = task
            except (KeyError, ValueError, TypeError, json.JSONDecodeError):
                continue

    def _save(self, task: Task) -> None:
        self.database.upsert_task(task)

    def create(self, description: str, **metadata: Any) -> Task:
        task = Task(description=description, metadata=metadata)
        self._tasks[task.id] = task
        self._save(task)
        return task

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def start(self, task_id: str) -> Task:
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

    def complete(self, task_id: str, result: Any = None) -> Task:
        task = self._tasks[task_id]
        if task.status != TaskStatus.RUNNING:
            raise RuntimeError(f"Tarefa {task_id} não pode ser concluída em estado {task.status.value}")
        task.status = TaskStatus.COMPLETED
        task.result = result
        task.finished_at = time()
        self._save(task)
        return task

    def fail(self, task_id: str, error: str) -> Task:
        task = self._tasks[task_id]
        if task.status != TaskStatus.RUNNING:
            raise RuntimeError(f"Tarefa {task_id} não pode falhar em estado {task.status.value}")
        task.status = TaskStatus.FAILED
        task.error = error
        task.finished_at = time()
        self._save(task)
        return task

    def cancel(self, task_id: str) -> Task:
        task = self._tasks[task_id]
        if task.status not in {TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.FAILED}:
            raise RuntimeError(f"Tarefa {task_id} não pode ser cancelada em estado {task.status.value}")
        task.status = TaskStatus.CANCELLED
        task.finished_at = time()
        self._save(task)
        return task

    def list(self, status: TaskStatus | None = None) -> list[Task]:
        tasks = list(self._tasks.values())
        if status is not None:
            tasks = [task for task in tasks if task.status == status]
        return sorted(tasks, key=lambda task: task.created_at)
