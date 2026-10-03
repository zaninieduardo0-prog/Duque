from __future__ import annotations

import os
import unittest
from typing import Any
from unittest import mock

from brain.agent_loop import AgentLoop
from brain.model import NullModel
from brain.self_development import SelfDevelopment
from computer.workspace import Workspace
from core.security import SecurityPolicy
from memory.memory import Memory
from tests.helpers import TempDirTestCase


class FakeForgeService:
    def __init__(self) -> None:
        self.goals: list[str] = []

    def submit(self, goal: str) -> dict[str, Any]:
        self.goals.append(goal)
        return {"id": "abc123", "goal": goal, "state": "queued", "position": 1}

    def status(self) -> dict[str, Any]:
        return {"current": None, "queued": len(self.goals), "history": []}


class AgentForgeTests(TempDirTestCase):
    def make_agent(self, forge: Any | None) -> AgentLoop:
        agent = AgentLoop(
            tasks=self.tasks,
            workspace=Workspace(self.tmp / "ws"),
            model=NullModel(),
            memory=Memory(self.database),
            forge_service=forge,
        )
        self.addCleanup(self._stop, agent)
        return agent

    @staticmethod
    def _stop(agent: AgentLoop) -> None:
        stop = getattr(agent.scheduled_runner, "stop", None)
        if callable(stop):
            stop()

    def test_self_improvement_requests_go_to_forge(self) -> None:
        forge = FakeForgeService()
        agent = self.make_agent(forge)
        result = agent.handle("Duque, melhore seu código de reconhecimento de apps")
        self.assertEqual(forge.goals, ["Duque, melhore seu código de reconhecimento de apps"])
        self.assertIn("Forja", result.text)
        self.assertIn("abc123", result.text)

    def test_forge_trigger_requires_a_change_request(self) -> None:
        should = [
            "Duque, melhore seu código de reconhecimento de apps",
            "coloque na forja: adicionar o Notion",
            "corrija o projeto, o timer não avisa",
            "adicione ao Duque um comando de tradução",
            "se atualize para entender datas melhor",
        ]
        should_not = [
            "explica seu código",
            "qual a linguagem do seu código?",
            "melhore esse texto para mim",
            "como está a forja?",
            "abre o projeto no vscode",
        ]
        for text in should:
            with self.subTest(text=text):
                self.assertTrue(AgentLoop._forge_requested(text))
        for text in should_not:
            with self.subTest(text=text):
                self.assertFalse(AgentLoop._forge_requested(text))

    def test_regular_requests_do_not_go_to_forge(self) -> None:
        forge = FakeForgeService()
        agent = self.make_agent(forge)
        agent.handle("leia o arquivo notas.txt")
        self.assertEqual(forge.goals, [])

    def test_forge_tools_are_available_to_the_agent(self) -> None:
        agent = self.make_agent(FakeForgeService())
        self.assertIn("forge_improve", agent.schemas.names())
        self.assertIn("forge_status", agent.executor.tools.names())

    def test_forge_is_off_without_git_repository(self) -> None:
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "", "OPENAI_API_KEY": ""}):
            agent = self.make_agent(None)
        self.assertIsNone(agent.forge_service)
        self.assertNotIn("forge_improve", agent.schemas.names())


class LiveEditPolicyTests(TempDirTestCase):
    def test_live_self_modification_is_off_by_default(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DUQUE_ALLOW_SELF_MODIFICATION", None)
            development = SelfDevelopment(Workspace(self.tmp / "ws"))
        result = development.apply_change("a.py", "x = 1")
        self.assertFalse(result["success"])
        self.assertIn("forge_improve", result["error"])
        self.assertFalse((self.tmp / "ws" / "a.py").exists())

    def test_live_commits_need_confirmation(self) -> None:
        policy = SecurityPolicy()
        self.assertTrue(policy.assess("git_commit").confirmation_required)
        self.assertTrue(policy.assess("apply_code_change").confirmation_required)
        self.assertFalse(policy.assess("forge_improve").confirmation_required)


if __name__ == "__main__":
    unittest.main()
