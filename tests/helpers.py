"""Utilitários compartilhados pelos testes do Duque.

Os testes não dependem de API, microfone, tela nem Windows: tudo que é externo
é substituído por dublês simples para validar a arquitetura de forma isolada.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from brain.model import ModelAdapter, ModelResponse
from core.tasks import TaskManager
from memory.database import MemoryDatabase


class ScriptedModel(ModelAdapter):
    """Modelo falso que devolve respostas pré-definidas em ordem."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[list[dict[str, str]]] = []

    def respond(self, messages: list[dict[str, str]], **kwargs: Any) -> ModelResponse:
        self.calls.append([dict(message) for message in messages])
        if not self.replies:
            raise RuntimeError("ScriptedModel sem respostas restantes")
        return ModelResponse(text=self.replies.pop(0))


class TempDirTestCase(unittest.TestCase):
    """Cria um diretório temporário isolado e um banco SQLite descartável."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.database = MemoryDatabase(self.tmp / "memory.db")
        self.tasks = TaskManager(self.database)

    def tearDown(self) -> None:
        self._tmp.cleanup()
