from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any


class MemoryDatabase:
    """Persistência SQLite local para memória e estado operacional do Duque."""

    def __init__(self, path: str | Path = "duque_data/memory.db") -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
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
                """
            )

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
            clauses.append("(key LIKE ? OR value LIKE ?)")
            pattern = f"%{query}%"
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
