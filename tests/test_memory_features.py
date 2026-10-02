from __future__ import annotations

import os
import unittest
from typing import Any
from unittest import mock

from brain.agent_loop import AgentLoop
from brain.model import NullModel
from brain.persona import text_system_prompt, voice_instructions
from computer.workspace import Workspace
from memory.memory import Memory
from tests.helpers import ScriptedModel, TempDirTestCase


def fake_weather(url: str) -> Any:
    if "geocoding" in url:
        return {"results": [{"name": "Piracicaba", "latitude": -22.7, "longitude": -47.6}]}
    return {
        "current": {"temperature_2m": 25.0, "apparent_temperature": 26.0, "weather_code": 0},
        "daily": {"temperature_2m_min": [17.0], "temperature_2m_max": [30.0], "precipitation_probability_max": [10]},
    }


class MemoryFeatureTests(TempDirTestCase):
    def make_agent(self, model: Any) -> AgentLoop:
        with mock.patch.dict(os.environ, {"DUQUE_FORGE": "0"}):
            agent = AgentLoop(tasks=self.tasks, workspace=Workspace(self.tmp / "ws"), model=model, memory=Memory(self.database))
        agent.assistant_tools.fetch_json = fake_weather
        self.addCleanup(agent.scheduled_runner.stop)
        return agent

    def test_remember_and_recall_by_text(self) -> None:
        agent = self.make_agent(NullModel())
        agent.handle("lembre que eu tomo café sem açúcar")
        result = agent.handle("o que você sabe sobre mim?")
        self.assertIn("eu tomo café sem açúcar", result.text)

    def test_notes_reach_the_model(self) -> None:
        model = ScriptedModel(["sem plano", "Sem açúcar, como sempre."])
        agent = self.make_agent(model)
        agent.assistant_tools.note_add("toma café sem açúcar")
        agent.handle("como eu gosto do café?")
        system = model.calls[-1][0]["content"]
        self.assertIn("O QUE VOCÊ SABE SOBRE O DU", system)
        self.assertIn("toma café sem açúcar", system)

    def test_persona_memory_block(self) -> None:
        self.assertNotIn("O QUE VOCÊ SABE", text_system_prompt(""))
        self.assertIn("- gosta de jazz", voice_instructions("", "- gosta de jazz"))

    def test_greeting(self) -> None:
        agent = self.make_agent(NullModel())
        agent.assistant_tools.note_add("x")
        text = agent.greeting()
        self.assertRegex(text, r"^(Bom dia|Boa tarde|Boa noite), Du\. São \d\d:\d\d\.")
        self.assertIn("Piracicaba: 25°C", text)
        self.assertIn("1 anotação", text)
        self.assertTrue(text.endswith("Sistemas online."))

    def test_greeting_survives_weather_failure(self) -> None:
        agent = self.make_agent(NullModel())

        def offline(url: str) -> Any:
            raise OSError("sem internet")

        agent.assistant_tools.fetch_json = offline
        self.assertTrue(agent.greeting().endswith("Sistemas online."))

    def test_forge_results_are_announced(self) -> None:
        agent = self.make_agent(NullModel())
        agent._forge_notify("forja_concluida", {"goal": "adicionar Notion", "status": "merged", "restarting": True})
        turn = agent.conversation.recent(1)[0]
        self.assertEqual(turn.channel, "aviso")
        self.assertIn("adicionar Notion", turn.text)
        self.assertIn("reiniciar", turn.text)
        self.assertIn("aprovação", AgentLoop.forge_announcement({"goal": "x", "status": "awaiting_approval"}))
        self.assertIn("não consegui", AgentLoop.forge_announcement({"goal": "x", "status": "failed"}))


if __name__ == "__main__":
    unittest.main()
