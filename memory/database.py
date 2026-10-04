from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any


DEFAULT_PATH = Path(__file__).resolve().parent.parent / "duque_data" / "memory.db"
# Histórico de conversa e tarefas encerradas mais antigos que isso são apagados
# ao abrir o banco, para ele não crescer sem limite.
RETENTION_DAYS = 30


class MemoryDatabase:
    """Persistência SQLite local para memória, tarefas e agendamentos."""

    def __init__(self, path: str | Path = DEFAULT_PATH, *, retention_days: float = RETENTION_DAYS) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._initialize()
        self.prune(retention_days)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Abre uma conexão, faz commit/rollback e sempre a fecha.

        `with sqlite3.connect(...)` sozinho só controla a transação e deixa a
        conexão aberta; no Windows isso mantém o arquivo travado.
        """
        connection = sqlite3.connect(self.path, check_same_thread=False, timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as db:
            # WAL deixa leituras e escritas de threads diferentes conviverem.
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    layer TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(layer, key)
                );
                CREATE INDEX IF NOT EXISTS idx_memories_layer ON memories(layer);

                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result TEXT,
                    error TEXT,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    finished_at REAL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);

                CREATE TABLE IF NOT EXISTS scheduled_jobs (
                    id TEXT PRIMARY KEY,
                    description TEXT NOT NULL,
                    run_at REAL NOT NULL,
                    repeat_seconds REAL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    last_run_at REAL,
                    run_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_due ON scheduled_jobs(enabled, run_at);
                """
            )

    def prune(self, retention_days: float) -> None:
        cutoff = time.time() - retention_days * 86400
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM memories WHERE layer='conversation' AND updated_at < ?", (cutoff,))
            db.execute("DELETE FROM memories WHERE layer='operational' AND updated_at < ?", (cutoff,))
            db.execute(
                "DELETE FROM tasks WHERE status IN ('completed','failed','cancelled') AND COALESCE(finished_at, created_at) < ?",
                (cutoff,),
            )
            db.execute("DELETE FROM scheduled_jobs WHERE enabled=0 AND COALESCE(last_run_at, created_at) < ?", (cutoff,))

    def set(self, layer: str, key: str, value: str, timestamp: float) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                """
                INSERT INTO memories(layer, key, value, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(layer, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (layer, key, value, timestamp, timestamp),
            )

    def get(self, layer: str, key: str) -> str | None:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT value FROM memories WHERE layer=? AND key=?", (layer, key)).fetchone()
        return row["value"] if row else None

    def search(self, layer: str | None = None, query: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        clauses: list[str] = []
        params: list[Any] = []
        if layer:
            clauses.append("layer=?")
            params.append(layer)
        if query:
            clauses.append("(key LIKE ? ESCAPE '\\' OR value LIKE ? ESCAPE '\\')")
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            params.extend([pattern, pattern])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock, self._connect() as db:
            rows = db.execute(
                f"SELECT id, layer, key, value, created_at, updated_at FROM memories {where} ORDER BY updated_at DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete(self, layer: str, key: str) -> bool:
        with self._lock, self._connect() as db:
            cursor = db.execute("DELETE FROM memories WHERE layer=? AND key=?", (layer, key))
            return cursor.rowcount > 0

    def upsert_task(self, task: Any) -> None:
        payload = json.dumps(task.result, ensure_ascii=False, default=str) if task.result is not None else None
        metadata = json.dumps(task.metadata, ensure_ascii=False, default=str)
        with self._lock, self._connect() as db:
            db.execute(
                """INSERT INTO tasks(id, description, status, result, error, created_at, started_at, finished_at, attempts, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET description=excluded.description, status=excluded.status,
                result=excluded.result, error=excluded.error, started_at=excluded.started_at,
                finished_at=excluded.finished_at, attempts=excluded.attempts, metadata=excluded.metadata""",
                (task.id, task.description, task.status.value, payload, task.error, task.created_at,
                 task.started_at, task.finished_at, task.attempts, metadata),
            )

    def load_tasks(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM tasks ORDER BY created_at ASC").fetchall()]

    def upsert_job(self, job: Any, created_at: float, last_run_at: float | None, run_count: int) -> None:
        metadata = json.dumps(job.metadata, ensure_ascii=False, default=str)
        with self._lock, self._connect() as db:
            db.execute(
                """INSERT INTO scheduled_jobs(id, description, run_at, repeat_seconds, enabled, metadata, created_at, last_run_at, run_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET description=excluded.description, run_at=excluded.run_at,
                repeat_seconds=excluded.repeat_seconds, enabled=excluded.enabled, metadata=excluded.metadata,
                last_run_at=excluded.last_run_at, run_count=excluded.run_count""",
                (job.id, job.description, job.run_at, job.repeat_seconds, int(job.enabled), metadata,
                 created_at, last_run_at, run_count),
            )

    def load_jobs(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM scheduled_jobs"
        if enabled_only:
            query += " WHERE enabled=1"
        query += " ORDER BY run_at ASC"
        with self._lock, self._connect() as db:
            return [dict(row) for row in db.execute(query).fetchall()]

    def delete_job(self, job_id: str) -> bool:
        with self._lock, self._connect() as db:
            cursor = db.execute("DELETE FROM scheduled_jobs WHERE id=?", (job_id,))
            return cursor.rowcount > 0
