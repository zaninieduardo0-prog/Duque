from __future__ import annotations

import importlib.util
import os
import unittest
from unittest import mock

from brain.persona import voice_instructions
from brain.planner import Planner
from brain.router import Intent, IntentRouter
from brain.voice_style import DEFAULT_VOICE, VOICES, current_voice, list_voices, set_voice
from computer.tools import ComputerTools
from memory.memory import Memory
from tests.helpers import TempDirTestCase


class FakeController:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def open_url(self, url: str) -> None:
        self.urls.append(url)


class SearchTests(unittest.TestCase):
    def plan(self, text: str):
        intent = IntentRouter().route(text).intent
        return intent, [(s.tool, s.arguments) for s in Planner().build(text, intent.value).steps]

    def test_open_google_when_asked(self) -> None:
        intent, steps = self.plan("Abra uma página no google, por aqui mesmo, e pesquise qual o atual presidente do Brasil")
        self.assertEqual(intent, Intent.SEARCH)
        self.assertEqual(steps, [("google_search", {"query": "qual o atual presidente do Brasil"})])

    def test_headless_search_falls_back_to_google(self) -> None:
        """Regressão: respondia "Nenhum resultado encontrado" em vez de abrir a pesquisa."""
        controller = FakeController()
        tools = ComputerTools(controller=controller)  # type: ignore[arg-type]
        with mock.patch("computer.tools.urlopen", side_effect=OSError("bloqueado")):
            result = tools.web_search("atual presidente do Brasil")
        self.assertTrue(result["opened"])
        self.assertIn("google.com/search?q=atual+presidente+do+Brasil", controller.urls[0])


class VoiceStyleTests(TempDirTestCase):
    def test_choose_and_persist_voice(self) -> None:
        memory = Memory(self.database)
        with mock.patch.dict(os.environ, {"DUQUE_VOICE": ""}):
            self.assertEqual(current_voice(memory), DEFAULT_VOICE)
            self.assertIn("ash", set_voice(memory, "Ash")["message"])
            self.assertEqual(current_voice(Memory(self.database)), "ash")
            self.assertFalse(set_voice(memory, "darth vader")["success"])
            self.assertEqual(list_voices(memory)["active"], "ash")

    def test_voice_commands(self) -> None:
        router, planner = IntentRouter(), Planner()
        for text, expected in {
            "mude sua voz para ash": [("set_voice", {"name": "ash"})],
            "quais vozes você tem?": [("list_voices", {})],
        }.items():
            with self.subTest(text=text):
                intent = router.route(text).intent
                self.assertEqual([(s.tool, s.arguments) for s in planner.build(text, intent.value).steps], expected)

    def test_voice_delivery_in_instructions(self) -> None:
        text = voice_instructions()
        self.assertIn("COMO FALAR", text)
        self.assertIn("Hey Jarvis", text)
        self.assertTrue(set(VOICES) >= {"ballad", "cedar", "ash"})


@unittest.skipUnless(importlib.util.find_spec("openai") is not None, "servidor exige o pacote openai")
class VoiceEndpointTests(unittest.TestCase):
    def test_voice_api(self) -> None:
        from tests.test_conversation import ServerConversationTests

        ServerConversationTests.setUpClass()
        try:
            client = ServerConversationTests.servidor.app.test_client()
            data = client.get("/api/voz").get_json()
            self.assertIn(data["atual"], VOICES)
            self.assertEqual(client.post("/api/voz", json={"voz": "echo"}).status_code, 200)
            self.assertEqual(client.get("/api/voz").get_json()["atual"], "echo")
            self.assertEqual(client.post("/api/voz", json={"voz": "xyz"}).status_code, 400)
        finally:
            ServerConversationTests.tearDownClass()


if __name__ == "__main__":
    unittest.main()
