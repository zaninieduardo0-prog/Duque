from __future__ import annotations

import os
import unittest
from typing import Any
from unittest import mock

from brain.agent_loop import AgentLoop
from computer.workspace import Workspace
from core.windows import CREATE_NO_WINDOW, hide_console_windows
from memory.memory import Memory
from tests.helpers import ScriptedModel, TempDirTestCase


class FakePopen:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.kwargs = kwargs


class HideConsoleTests(unittest.TestCase):
    def test_windows_gets_no_window_flag(self) -> None:
        cls = type("Popen", (FakePopen,), {})
        self.assertTrue(hide_console_windows(cls, platform="win32"))
        self.assertEqual(cls(["tasklist"]).kwargs["creationflags"], CREATE_NO_WINDOW)
        self.assertEqual(cls(["x"], creationflags=0x10).kwargs["creationflags"], 0x10)
        self.assertTrue(hide_console_windows(cls, platform="win32"))  # idempotente

    def test_other_platforms_untouched(self) -> None:
        cls = type("Popen", (FakePopen,), {})
        self.assertFalse(hide_console_windows(cls, platform="linux"))
        self.assertNotIn("creationflags", cls(["ls"]).kwargs)


class SmallTalkTests(TempDirTestCase):
    def test_detection(self) -> None:
        for text in ("Bom dia", "bom dia, Duque!", "Oi Duque, tudo bem?", "valeu", "e aí jarvis, beleza?"):
            with self.subTest(text=text):
                self.assertTrue(AgentLoop._is_small_talk(text))
        for text in ("bom dia, que horas são?", "me conta uma piada", "abre o spotify", ""):
            with self.subTest(text=text):
                self.assertFalse(AgentLoop._is_small_talk(text))

    def test_greeting_never_calls_tools(self) -> None:
        """Regressão: "Bom dia" era respondido com a hora pelo planejador do modelo."""
        # Com o bug, o planejador consumiria esta resposta e a conversa ficaria sem nenhuma.
        model = ScriptedModel(["Bom dia, Du."])
        with mock.patch.dict(os.environ, {"DUQUE_FORGE": "0", "DUQUE_DAILY_SUMMARY": "0"}):
            agent = AgentLoop(tasks=self.tasks, workspace=Workspace(self.tmp / "ws"), model=model, memory=Memory(self.database))
        self.addCleanup(agent.scheduled_runner.stop)
        result = agent.handle("Bom dia")
        self.assertEqual(result.text, "Bom dia, Du.")
        self.assertEqual(len(model.calls), 1)  # só a resposta de conversa, sem planejamento


if __name__ == "__main__":
    unittest.main()
