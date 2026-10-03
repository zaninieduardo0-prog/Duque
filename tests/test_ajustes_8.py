"""Ajustes 8: logo do Du, letras menores, HUD que reconecta e lembretes que não viram instrução."""

from __future__ import annotations

import importlib.util
import re
import unittest
from pathlib import Path

from computer.assistant_tools import MAX_REMINDER_TEXT, AssistantTools

HTML = (Path(__file__).resolve().parent.parent / "interface" / "index.html").read_text(encoding="utf-8")


class HudTests(unittest.TestCase):
    def test_logo_is_the_image_sent(self) -> None:
        self.assertRegex(HTML, r'<div id="logo"[^>]*><img src="data:image/png;base64,[A-Za-z0-9+/=]{1000,}" alt="TELEX"')
        self.assertTrue((Path(__file__).resolve().parent.parent / "interface" / "telex_logo.png").exists())

    def test_center_texts_are_small(self) -> None:
        state = re.search(r"#stateName\{[^}]*?font-size:(\d+(?:\.\d+)?)px", HTML, re.S)
        assert state is not None
        self.assertLessEqual(float(state.group(1)), 12)
        self.assertIn("#keys{margin-top:10px;font-size:7.5px", HTML)

    def test_dock_respects_left_column(self) -> None:
        self.assertIn("function dockBounds()", HTML)

    def test_reconnects_and_reloads(self) -> None:
        self.assertIn("sua mensagem será enviada assim que ele voltar", HTML)
        self.assertIn("/api/versao", HTML)


class ReminderGuardTests(unittest.TestCase):
    def test_instruction_is_not_a_reminder(self) -> None:
        tools = AssistantTools()
        instruction = "Organize o restante do dia do Du. Verifique agenda, compromissos, tarefas, lembretes e prazos e crie um plano simples com horários sugeridos."
        self.assertGreater(len(instruction), MAX_REMINDER_TEXT)
        self.assertFalse(tools.timer_set(60, instruction).get("success", True))
        ok = tools.timer_set(60, "tomar água")
        self.assertNotEqual(ok.get("success"), False)
        tools.timer_cancel()


@unittest.skipUnless(importlib.util.find_spec("openai") is not None, "servidor exige o pacote openai")
class VersionEndpointTests(unittest.TestCase):
    def test_version(self) -> None:
        from tests.test_conversation import ServerConversationTests

        ServerConversationTests.setUpClass()
        try:
            client = ServerConversationTests.servidor.app.test_client()
            first = client.get("/api/versao").get_json()["versao"]
            self.assertTrue(first)
            self.assertEqual(first, client.get("/api/versao").get_json()["versao"])
        finally:
            ServerConversationTests.tearDownClass()


if __name__ == "__main__":
    unittest.main()
