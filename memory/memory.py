from __future__ import annotations

import json
from dataclasses import dataclass
from time import time
from typing import Any

from .database import MemoryDatabase


class MemoryLayer:
    CONVERSATION = "conversation"
    PERSONAL = "personal"
    OPERATIONAL = "operational"
    KNOWLEDGE = "knowledge"


@dataclass(slots=True, frozen=True)
class MemoryItem:
    layer: str
    key: str
    value: Any
    updated_at: float


class Memory:
    """API de memória sem acoplar o restante do Duque ao SQLite."""

    def __init__(self, database: MemoryDatabase | None = None) -> None:
        self.database = database or MemoryDatabase()

    def remember(self, layer: str, key: str, value: Any) -> MemoryItem:
        timestamp = time()
        # Sempre JSON: antes um texto como "123" ou "true" era gravado cru e
        # voltava como número/booleano no recall.
        encoded = json.dumps(value, ensure_ascii=False, default=str)
        self.database.set(layer, key, encoded, timestamp)
        return MemoryItem(layer, key, value, timestamp)

    def recall(self, layer: str, key: str, default: Any = None) -> Any:
        value = self.database.get(layer, key)
        if value is None:
            return default
        return self._decode(value)

    def search(self, layer: str | None = None, query: str | None = None, limit: int = 20) -> list[MemoryItem]:
        return [MemoryItem(item["layer"], item["key"], self._decode(item["value"]), item["updated_at"]) for item in self.database.search(layer, query, limit)]

    def forget(self, layer: str, key: str) -> bool:
        return self.database.delete(layer, key)

    @staticmethod
    def _decode(value: str) -> Any:
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value  # gravado cru por versões antigas
