from __future__ import annotations

import json
import unittest

from brain.autonomous_loop import AutonomousLoop
from brain.agent_state import AgentContext
from brain.model_planner import ModelPlanner
from brain.planner import StepKind
from brain.router import Intent, IntentRouter
from brain.self_correction import SelfCorrection
from brain.tool_schema import ToolSchemaRegistry, ToolSpec
from core.executor import Executor
from core.task_engine import TaskEngine
from core.tasks import TaskStatus
from tests.helpers import ScriptedModel, TempDirTestCase


def tool(name: str, **arguments) -> str:
    return json.dumps({"action": "tool", "tool": name, "arguments": arguments})


def finish(message: str) -> str:
    return json.dumps({"action": "finish", "message": message})


class ToolSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schemas = ToolSchemaRegistry()
        self.schemas.register(ToolSpec("write_file", "escreve", ("path", "content"), {"path": str, "content": str}))

    def test_valid_arguments(self) -> None:
        self.assertTrue(self.schemas.validate("write_file", {"path": "a.txt", "content": "x"}).valid)

    def test_missing_argument(self) -> None:
        result = self.schemas.validate("write_file", {"path": "a.txt"})
        self.assertFalse(result.valid)
        self.assertIn("content", result.error or "")

    def test_unexpected_argument(self) -> None:
        result = self.schemas.validate("write_file", {"path": "a", "content": "b", "extra": 1})
        self.assertFalse(result.valid)

    def test_wrong_type(self) -> None:
        self.assertFalse(self.schemas.validate("write_file", {"path": 1, "content": "b"}).valid)

    def test_unknown_tool(self) -> None:
        self.assertFalse(self.schemas.validate("nao_existe", {}).valid)


class RouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = IntentRouter()

    def test_routes(self) -> None:
        cases = {
            "abra o chrome": Intent.OPEN_APP,
            "feche o chrome": Intent.CLOSE_APP,
            "pesquise o clima de amanhã": Intent.SEARCH,
            "leia o arquivo notas.txt": Intent.FILE_OPERATION,
            "me lembre de beber água": Intent.REMINDER,
            "aumente o volume": Intent.SYSTEM,
            "como você está?": Intent.CHAT,
            "": Intent.UNKNOWN,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.router.route(text).intent, expected)

    def test_context_app_enables_status_question(self) -> None:
        self.assertEqual(self.router.route("ele está aberto?", context_app="chrome").intent, Intent.CHECK_APP)


class ModelPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schemas = ToolSchemaRegistry()
        self.schemas.register(ToolSpec("open_app", "abre", ("name",), {"name": str}))

    def test_parses_fenced_json_plan(self) -> None:
        plan_json = json.dumps({"goal": "abrir", "steps": [{"description": "abrir", "kind": "tool", "tool": "open_app", "arguments": {"name": "chrome"}}]})
        planner = ModelPlanner(ScriptedModel([f"```json\n{plan_json}\n```"]), self.schemas)
        plan = planner.build("abra o chrome")
        self.assertEqual(plan.steps[0].kind, StepKind.TOOL)
        self.assertEqual(plan.steps[0].arguments, {"name": "chrome"})

    def test_rejects_tool_outside_allowed_list(self) -> None:
        plan_json = json.dumps({"steps": [{"kind": "tool", "tool": "open_app", "arguments": {"name": "x"}}]})
        planner = ModelPlanner(ScriptedModel([plan_json]), self.schemas)
        with self.assertRaises(ValueError):
            planner.build("x", available_tools=[])

    def test_rejects_invalid_json(self) -> None:
        planner = ModelPlanner(ScriptedModel(["não é json"]), self.schemas)
        with self.assertRaises(ValueError):
            planner.build("x")


class AutonomousLoopTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.executor = Executor(self.tasks)
        self.schemas = ToolSchemaRegistry()
        self.files: dict[str, str] = {}

        def write_file(path: str, content: str) -> dict:
            self.files[path] = content
            return {"path": path, "created": True}

        def run_tests() -> dict:
            ok = "corrigido" in self.files.get("app.py", "")
            return {"success": ok, "stdout": "1 passed" if ok else "", "stderr": "" if ok else "1 failed"}

        self.executor.register("write_file", write_file)
        self.executor.register("run_tests", run_tests)
        self.executor.register("git_push", lambda: {"pushed": True})
        self.schemas.register(ToolSpec("write_file", "", ("path", "content"), {"path": str, "content": str}))
        self.schemas.register(ToolSpec("run_tests", ""))
        self.schemas.register(ToolSpec("git_push", ""))

    def _run(self, replies: list[str], **kwargs):
        model = ScriptedModel(replies)
        loop = AutonomousLoop(model, self.executor, self.schemas, **kwargs)
        task = self.tasks.create("objetivo")
        self.tasks.start(task.id)
        return loop.run(AgentContext(goal="corrigir app", task_id=task.id)), model

    def test_finish_without_evidence_is_rejected(self) -> None:
        result, model = self._run([
            finish("pronto"),
            tool("write_file", path="app.py", content="corrigido"),
            tool("run_tests"),
            finish("testes passando"),
        ])
        self.assertTrue(result.success)
        self.assertIn("AÇÃO REJEITADA", model.calls[1][-1]["content"])
        self.assertEqual(result.steps, 3)

    def test_finish_after_failed_tool_is_rejected(self) -> None:
        result, _ = self._run([
            tool("write_file", path="app.py", content="bug"),
            tool("run_tests"),
            finish("acho que deu certo"),
            tool("write_file", path="app.py", content="corrigido"),
            tool("run_tests"),
            finish("agora sim"),
        ])
        self.assertTrue(result.success)
        self.assertEqual(result.message, "agora sim")

    def test_invalid_tool_arguments_are_rejected_without_execution(self) -> None:
        result, model = self._run([
            tool("write_file", path="app.py"),
            tool("write_file", path="app.py", content="corrigido"),
            tool("run_tests"),
            finish("ok"),
        ])
        self.assertTrue(result.success)
        self.assertIn("ausentes", model.calls[1][-1]["content"])

    def test_repeated_action_loop_is_stopped(self) -> None:
        result, _ = self._run([tool("run_tests")] * 5)
        self.assertFalse(result.success)
        self.assertIn("Loop detectado", result.error or "")

    def test_high_risk_action_stops_for_confirmation(self) -> None:
        result, _ = self._run([tool("git_push")])
        self.assertFalse(result.success)
        self.assertTrue(result.executions[-1].confirmation_required)

    def test_step_limit(self) -> None:
        result, _ = self._run(["lixo"] * 3, max_steps=3)
        self.assertFalse(result.success)
        self.assertIn("Limite", result.error or "")


class SelfCorrectionTests(TempDirTestCase):
    def test_retries_with_error_until_success(self) -> None:
        executor = Executor(self.tasks)
        executor.register("ok", lambda: "feito")
        executor.register("ruim", lambda: {"success": False, "error": "caminho errado"})
        correction = SelfCorrection(TaskEngine(executor))
        seen_errors: list[str | None] = []

        def factory(error, attempt):
            seen_errors.append(error)
            return [("ruim", {})] if attempt == 1 else [("ok", {})]

        task = self.tasks.create("corrigir")
        report = correction.run(task, factory, max_attempts=3)

        self.assertTrue(report.success)
        self.assertEqual(report.attempts, 2)
        self.assertEqual(seen_errors, [None, "caminho errado"])
        self.assertEqual(task.status, TaskStatus.COMPLETED)

    def test_gives_up_after_max_attempts(self) -> None:
        executor = Executor(self.tasks)
        executor.register("ruim", lambda: {"success": False, "error": "sempre falha"})
        report = SelfCorrection(TaskEngine(executor)).run(self.tasks.create("x"), lambda e, a: [("ruim", {})], max_attempts=2)
        self.assertFalse(report.success)
        self.assertEqual(report.attempts, 2)
        self.assertEqual(report.last_error, "sempre falha")

    def test_retry_does_not_reopen_what_already_opened(self) -> None:
        executor = Executor(self.tasks)
        opened: list[str] = []
        executor.register("open_app", lambda name: opened.append(name) or {"opened": True})
        attempts = {"n": 0}

        def flaky() -> dict[str, object]:
            attempts["n"] += 1
            return {"success": attempts["n"] > 1, "error": "ainda carregando"}

        executor.register("digitar", flaky)
        steps = [("open_app", {"name": "chrome"}), ("digitar", {})]
        report = SelfCorrection(TaskEngine(executor)).run(self.tasks.create("x"), lambda e, a: steps, max_attempts=3)

        self.assertTrue(report.success)
        self.assertEqual(report.attempts, 2)
        self.assertEqual(opened, ["chrome"])


if __name__ == "__main__":
    unittest.main()
