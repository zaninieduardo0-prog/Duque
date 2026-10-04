from __future__ import annotations

import json
from unittest import mock

from brain import agent_loop as agent_module
from brain.agent_loop import AgentLoop
from computer.workspace import Workspace
from core.tasks import TaskStatus
from tests.helpers import ScriptedModel, TempDirTestCase


def plan(*steps: tuple[str, dict]) -> str:
    return json.dumps({"goal": "x", "steps": [{"kind": "tool", "tool": tool, "arguments": args} for tool, args in steps]})


def answer(text: str) -> str:
    return json.dumps({"answer": text, "steps": []})


class AgentLoopTests(TempDirTestCase):
    def make(self, replies: list[str]) -> tuple[AgentLoop, ScriptedModel, list[tuple[str, dict]]]:
        model = ScriptedModel(replies)
        loop = AgentLoop(tasks=self.tasks, workspace=Workspace(self.tmp), model=model)
        calls: list[tuple[str, dict]] = []

        def fake(name: str):
            def tool(**kwargs):
                calls.append((name, kwargs))
                return {"ok": True, "tool": name}
            return tool

        for name in ("run_command", "open_url", "kill_process"):
            loop.executor.register(name, fake(name))
        return loop, model, calls

    def test_chat_answer_comes_from_single_planner_call(self) -> None:
        loop, model, calls = self.make([answer("Tudo ótimo, Du!")])
        result = loop.handle("oi, tudo bem?")
        self.assertEqual(result.text, "Tudo ótimo, Du!")
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(calls, [])

    def test_confirmation_runs_only_the_approved_step(self) -> None:
        loop, _model, calls = self.make([plan(("run_command", {"command": "dir"}))])
        result = loop.handle("rode dir")
        self.assertTrue(result.awaiting_confirmation)
        self.assertIn("run_command", result.text)
        self.assertEqual(calls, [])
        loop.handle("Sim.")
        self.assertEqual(calls, [("run_command", {"command": "dir"})])

    def test_unrelated_message_cancels_pending_confirmation(self) -> None:
        loop, _model, calls = self.make([plan(("run_command", {"command": "dir"})), answer("Ok.")])
        pending = loop.handle("rode dir")
        result = loop.handle("deixa, me conta uma piada")
        self.assertIn("Cancelei", result.text)
        self.assertFalse(loop.awaiting_confirmation)
        self.assertEqual(self.tasks.get(pending.task_id or "").status, TaskStatus.CANCELLED)
        self.assertEqual(calls, [])

    def test_expired_confirmation_is_not_executed(self) -> None:
        loop, _model, calls = self.make([plan(("run_command", {"command": "dir"})), answer("Oi.")])
        loop.handle("rode dir")
        with mock.patch.object(agent_module, "time", return_value=agent_module.time() + 3600):
            result = loop.handle("sim")
        self.assertIn("expirou", result.text)
        self.assertEqual(calls, [])

    def test_schedule_rejects_tight_repeat_and_risky_steps(self) -> None:
        loop, _model, _calls = self.make([])
        with self.assertRaises(ValueError):
            loop._schedule_task("spam", 0, [{"tool": "open_url", "arguments": {"url": "https://x.com"}}], repeat_seconds=1)
        with self.assertRaises(ValueError):
            loop._schedule_task("perigo", 0, [{"tool": "run_command", "arguments": {"command": "dir"}}])
        job = loop._schedule_task("ok", 60, [{"tool": "open_url", "arguments": {"url": "https://x.com"}}], repeat_seconds=3600)
        self.assertTrue(job["scheduled"])

    def test_scheduler_does_not_start_in_constructor(self) -> None:
        loop, _model, _calls = self.make([])
        self.assertIsNone(loop.scheduler._thread)

    def test_offline_chat_does_not_echo_user_text(self) -> None:
        loop = AgentLoop(tasks=self.tasks, workspace=Workspace(self.tmp), model=agent_module.NullModel())
        result = loop.handle("oi tudo bem?")
        self.assertNotEqual(result.text, "oi tudo bem?")
        self.assertIn("OPENAI_API_KEY", result.text)
