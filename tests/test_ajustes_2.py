from __future__ import annotations

import unittest
from typing import Any
from unittest import mock

from brain.model_planner import ModelPlanner
from brain.planner import Planner
from brain.router import Intent, IntentRouter
from brain.tool_schema import ToolSchemaRegistry, ToolSpec
from computer.tools import ComputerTools
from tests.helpers import ScriptedModel


class FakeController:
    def __init__(self) -> None:
        self.launched: list[list[str]] = []

    def launch(self, command: list[str]) -> None:
        self.launched.append(list(command))


class OpenAppTests(unittest.TestCase):
    def tools(self, running: list[bool]) -> ComputerTools:
        tools = ComputerTools(controller=FakeController())  # type: ignore[arg-type]
        tools.verify_seconds = 0.05
        tools.is_app_running = lambda name: {"running": running.pop(0) if running else False}  # type: ignore[method-assign]
        return tools

    def test_understands_possessive_names(self) -> None:
        tools = self.tools([True])
        with mock.patch("platform.system", return_value="Windows"):
            result = tools.open_app("minha calculadora")
        self.assertEqual(result["app"], "calculadora")
        self.assertTrue(result["verified"])

    def test_reports_when_app_never_appears(self) -> None:
        """Regressão: dizia "abri a calculadora" sem ela abrir."""
        tools = self.tools([])
        with mock.patch("platform.system", return_value="Windows"):
            result = tools.open_app("calculadora")
        self.assertFalse(result["success"])
        self.assertIn("não vi o processo", result["error"])

    def test_unknown_app_still_fails(self) -> None:
        with self.assertRaises(ValueError):
            self.tools([]).open_app("geladeira")


class ReferenceTests(unittest.TestCase):
    def test_reopen_last_app(self) -> None:
        route = IntentRouter().route("não achei aqui, abra novamente", context_app="calculadora")
        self.assertEqual(route.intent, Intent.OPEN_APP)
        plan = Planner().build("não achei aqui, abra novamente", route.intent.value, context_app="calculadora")
        self.assertEqual([(s.tool, s.arguments) for s in plan.steps], [("open_app", {"name": "calculadora"})])

    def test_model_planner_receives_conversation(self) -> None:
        schemas = ToolSchemaRegistry()
        schemas.register(ToolSpec("open_app", "abre", ("name",), {"name": str}))
        model = ScriptedModel(['{"steps":[{"kind":"tool","tool":"open_app","arguments":{"name":"calculadora"}}]}'])
        ModelPlanner(model, schemas).build("abre de novo", context="Du (texto): abra minha calculadora")
        self.assertIn("abra minha calculadora", model.calls[0][1]["content"])


class VoiceStartupTests(unittest.TestCase):
    def test_system_exit_is_logged(self) -> None:
        """Regressão: SystemExit na voz não era registrado e o Hey Jarvis morria calado."""
        import importlib.util
        import sys

        root = __import__("pathlib").Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location("duque_launcher_teste", root / "duque.py")
        assert spec and spec.loader
        source = (root / "duque.py").read_text(encoding="utf-8")
        start = source.index("def start_voice")
        end = source.index("\ndef ", start + 10)
        namespace: dict[str, Any] = {}
        exec(compile(source[start:end], "duque.py", "exec"), namespace)
        logs: list[str] = []

        class Runtime:
            log = staticmethod(logs.append)

            @staticmethod
            def wake_loop() -> None:
                raise SystemExit("OPENAI_API_KEY não encontrada")

        namespace["start_voice"](Runtime)
        self.assertTrue(any("SystemExit" in line and "OPENAI_API_KEY" in line for line in logs), logs)
        self.assertIsNotNone(sys)


if __name__ == "__main__":
    unittest.main()
