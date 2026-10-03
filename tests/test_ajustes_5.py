"""Ajustes 5: portão de audição, Chrome com o perfil do Du e WhatsApp sem repetição."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from computer.chrome import chrome_command, find_profile
from computer.tools import ComputerTools
from voice.gate import ListenGate, addressed, ends_with_question, is_stop

LOCAL_STATE = {
    "profile": {
        "last_used": "Default",
        "info_cache": {
            "Default": {"name": "Pessoa 1", "user_name": "outra.conta@gmail.com"},
            "Profile 2": {"name": "Du", "user_name": "zaninieduardo0@gmail.com"},
            "Profile 3": {"name": "Trabalho", "gaia_name": "Empresa"},
        },
    }
}


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class GateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = Clock()
        self.gate = ListenGate(clock=self.clock)

    def test_first_phrase_after_hey_jarvis_needs_no_name(self) -> None:
        self.gate.open(12)
        self.assertEqual(self.gate.decide("abra o whatsapp").action, "respond")

    def test_locks_after_a_command(self) -> None:
        """Pedido do Du: depois de "Telex, abra o WhatsApp" o som ambiente não conta."""
        self.gate.open(12)
        self.gate.decide("Telex, abra o whatsapp")
        self.assertEqual(self.gate.decide("e aí, tudo bem com você?").action, "ignore")
        self.assertEqual(self.gate.decide("Telex, que horas são?").action, "respond")

    def test_open_window_expires(self) -> None:
        self.gate.open(12)
        self.clock.now += 13
        self.assertEqual(self.gate.decide("abra o whatsapp").action, "ignore")

    def test_stop_interrupts(self) -> None:
        for phrase in ("Telex, stop", "Telex, para!", "para, Telex", "Telex, chega", "Telex, para de falar aí", "Teles stop"):
            with self.subTest(phrase=phrase):
                self.assertEqual(self.gate.decide(phrase, speaking=True).action, "stop")

    def test_stop_without_name_is_background(self) -> None:
        self.assertEqual(self.gate.decide("para com isso", speaking=True).action, "ignore")

    def test_calling_name_while_speaking_stops(self) -> None:
        """O Duque acima de tudo: chamou durante a explicação, ele para na hora."""
        decision = self.gate.decide("Telex!", speaking=True)
        self.assertEqual(decision.action, "stop")
        self.assertTrue(self.gate.is_open)  # e já escuta o próximo pedido
        self.assertEqual(self.gate.decide("abre o spotify").action, "respond")

    def test_name_with_preposition_para_is_a_request(self) -> None:
        self.assertEqual(self.gate.decide("Telex, manda mensagem para a Ana").action, "respond")

    def test_helpers(self) -> None:
        self.assertTrue(addressed("Ei Telex"))
        # Um nome só: "Duque" e "Jarvis" não chamam mais.
        self.assertFalse(addressed("Ei Duque"))
        self.assertFalse(addressed("Hey Jarvis"))
        self.assertFalse(addressed("o telefone"))
        self.assertTrue(is_stop("telex pare"))
        self.assertTrue(ends_with_question("Para quem? "))
        self.assertFalse(ends_with_question("Pronto."))


class ChromeProfileTests(unittest.TestCase):
    def test_finds_profile_by_email(self) -> None:
        self.assertEqual(find_profile(LOCAL_STATE, "Zaninieduardo0"), "Profile 2")

    def test_finds_profile_by_folder_or_name(self) -> None:
        self.assertEqual(find_profile(LOCAL_STATE, "Profile 3"), "Profile 3")
        self.assertEqual(find_profile(LOCAL_STATE, "empresa"), "Profile 3")

    def test_falls_back_to_last_used(self) -> None:
        self.assertEqual(find_profile(LOCAL_STATE, "ninguem"), "Default")

    def test_command_uses_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exe = root / "Google/Chrome/Application/chrome.exe"
            exe.parent.mkdir(parents=True)
            exe.write_text("")
            data = root / "Google/Chrome/User Data"
            data.mkdir(parents=True)
            (data / "Local State").write_text(json.dumps(LOCAL_STATE), encoding="utf-8")
            env = {"LOCALAPPDATA": tmp, "ProgramFiles": str(root / "x"), "ProgramFiles(x86)": str(root / "y")}
            command = chrome_command("https://web.whatsapp.com/", env)
        self.assertEqual(command, [str(exe), "--profile-directory=Profile 2", "https://web.whatsapp.com/"])

    def test_no_chrome_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(chrome_command("https://x", {"LOCALAPPDATA": tmp, "ProgramFiles": tmp, "ProgramFiles(x86)": tmp}))


class FakeController:
    def __init__(self) -> None:
        self.launched: list[list[str]] = []
        self.urls: list[str] = []

    def launch(self, command: list[str]) -> None:
        self.launched.append(list(command))

    def open_url(self, url: str) -> None:
        self.urls.append(url)

    def open_chrome(self) -> bool:
        self.urls.append("chrome")
        return True


class WhatsAppTests(unittest.TestCase):
    def tools(self) -> tuple[ComputerTools, FakeController]:
        controller = FakeController()
        tools = ComputerTools(controller=controller)  # type: ignore[arg-type]
        tools.verify_seconds = 0.05
        tools.is_app_running = lambda name: {"running": False}  # type: ignore[method-assign]
        return tools, controller

    def test_not_installed_opens_web_in_chrome(self) -> None:
        tools, controller = self.tools()
        with mock.patch("platform.system", return_value="Windows"), mock.patch("computer.apps.protocol_registered", return_value=False):
            result = tools.open_app("whatsapp")
        self.assertEqual(controller.urls, ["https://web.whatsapp.com/"])
        self.assertEqual(controller.launched, [])
        self.assertTrue(result["web"])

    def test_installed_but_slow_is_launched_once(self) -> None:
        """Regressão: o Duque tentava abrir o WhatsApp "a todo custo"."""
        tools, controller = self.tools()
        with mock.patch("platform.system", return_value="Windows"), mock.patch("computer.apps.protocol_registered", return_value=True):
            result: dict[str, Any] = tools.open_app("whatsapp")
        self.assertEqual(len(controller.launched), 1)
        self.assertNotIn("success", result)

    def test_new_whatsapp_process_name(self) -> None:
        from computer.apps import PROCESS_NAMES

        self.assertIn("whatsapp.root.exe", PROCESS_NAMES["whatsapp"])

    def test_sites_open_in_chrome_profile(self) -> None:
        tools, controller = self.tools()
        tools.open_app("youtube")
        self.assertEqual(controller.urls, ["https://www.youtube.com"])

    def test_web_alternative_for_message(self) -> None:
        from computer.assistant_tools import web_alternative

        self.assertEqual(web_alternative("whatsapp://send?phone=5519&text=oi"), "https://web.whatsapp.com/send?phone=5519&text=oi")
        self.assertIsNone(web_alternative("https://x"))


class NoRetryTests(unittest.TestCase):
    def test_open_app_failure_is_not_retried(self) -> None:
        from brain.self_correction import SelfCorrection
        from core.executor import ExecutionResult
        from core.task_engine import StepResult

        engine = mock.Mock()
        engine.run.return_value = [StepResult(0, "open_app", ExecutionResult(False, error="falhou"))]
        engine.succeeded.return_value = False
        calls: list[int] = []

        def factory(_error: str | None, attempt: int) -> list[tuple[str, dict[str, Any]]]:
            calls.append(attempt)
            return [("open_app", {"name": "whatsapp"})]

        report = SelfCorrection(engine).run(mock.Mock(), factory, max_attempts=3)
        self.assertFalse(report.success)
        self.assertEqual(calls, [1])


class BridgeStopTests(unittest.TestCase):
    def test_stop_speech_calls_session(self) -> None:
        from core.voice_bridge import VoiceBridge

        bridge = VoiceBridge()
        self.assertFalse(bridge.stop_speech())
        calls: list[int] = []
        bridge.attach_session(lambda _text: True, lambda: calls.append(1))
        self.assertTrue(bridge.stop_speech())
        self.assertEqual(calls, [1])


@unittest.skipUnless(importlib.util.find_spec("openai") is not None, "servidor exige o pacote openai")
class HudEndpointTests(unittest.TestCase):
    def test_open_and_stop_endpoints(self) -> None:
        from tests.test_conversation import ServerConversationTests

        ServerConversationTests.setUpClass()
        try:
            client = ServerConversationTests.servidor.app.test_client()
            self.assertEqual(client.post("/api/abrir", json={"app": "rm -rf"}).status_code, 400)
            with mock.patch("computer.tools.ComputerTools.open_app", return_value={"app": "whatsapp", "opened": True, "command": ["x"]}):
                data = client.post("/api/abrir", json={"app": "WhatsApp"}).get_json()
            self.assertTrue(data["ok"])
            self.assertNotIn("command", data)
            self.assertEqual(client.post("/api/parar").status_code, 200)
        finally:
            ServerConversationTests.tearDownClass()


if __name__ == "__main__":
    unittest.main()
