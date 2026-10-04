"""Ajustes 19: WhatsApp pelo jeito que o Du fala, perguntas sem chamada extra e início com a configuração atual."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

from brain.planner import WHATSAPP_ACTION
from computer.whatsapp_flow import parse_request, set_known_names
from tests.helpers import TempDirTestCase

ROOT = Path(__file__).resolve().parent.parent


class WhatsAppPhrasingTests(unittest.TestCase):
    CASES = {
        "manda uma mensagem pro João dizendo que vou atrasar": ("João", "vou atrasar"),
        "envia no zap pra Maria oi tudo bem": ("Maria", "oi tudo bem"),
        "manda um oi pra Maria no zap": ("Maria", "oi"),
        "chama o João no whatsapp e fala que eu cheguei": ("João", "eu cheguei"),
        "fala pro João no whats que a reunião foi adiada": ("João", "a reunião foi adiada"),
        "responde o João no whatsapp dizendo ok": ("João", "ok"),
        "manda um zap pro Carlos avisando que vou me atrasar": ("Carlos", "vou me atrasar"),
        "telex manda mensagem para minha mãe dizendo que chego tarde": ("mãe", "chego tarde"),
        "avisa o Pedro que o pedido saiu": ("Pedro", "o pedido saiu"),
        "mande uma mensagem pra Ana: a reunião é às três": ("Ana", "a reunião é às três"),
    }

    def test_phrases_are_understood(self) -> None:
        for text, (contact, message) in self.CASES.items():
            with self.subTest(text=text):
                request = parse_request(text)
                assert request is not None
                self.assertEqual((request.contact, request.text), (contact, message))
                self.assertTrue(request.send)

    def test_router_and_planner_recognize_them(self) -> None:
        # "avisa o Pedro que..." sem citar WhatsApp/mensagem fica de fora: pode ser um lembrete.
        for text in (t for t in self.CASES if not t.startswith("avisa")):
            with self.subTest(text=text):
                self.assertTrue(WHATSAPP_ACTION.search(text.casefold()))

    def test_name_with_two_words_uses_the_contact_book(self) -> None:
        try:
            set_known_names(lambda: ["Maria Clara"])
            request = parse_request("manda pra Maria Clara oi, tudo bem")
            assert request is not None
            self.assertEqual((request.contact, request.text), ("Maria Clara", "oi, tudo bem"))
        finally:
            set_known_names(lambda: [])

    def test_not_a_message(self) -> None:
        for text in ("que horas são", "abra o chrome", "toque rock no youtube", "me explique o que é o whatsapp"):
            with self.subTest(text=text):
                self.assertIsNone(parse_request(text))

    def test_unsplittable_tail_is_not_guessed(self) -> None:
        self.assertIsNone(parse_request("manda pra Fulano xyz abc"))  # sem como separar nome e texto: não chuta


class AgentSendTests(TempDirTestCase):
    def test_voice_phrasing_reaches_the_whatsapp_tool(self) -> None:
        from brain.agent_loop import AgentLoop
        from brain.model import NullModel
        from computer.workspace import Workspace
        from memory.memory import Memory

        with mock.patch.dict(os.environ, {"DUQUE_FORGE": "0"}):
            agent = AgentLoop(tasks=self.tasks, workspace=Workspace(self.tmp / "ws"), model=NullModel(), memory=Memory(self.database))
        self.addCleanup(agent.scheduled_runner.stop)
        sent: list[tuple[str, str]] = []
        agent.executor.register(
            "whatsapp_send",
            lambda contact, text, hint="", send=True, profile="": sent.append((contact, text)) or {"message": "ok"},
        )
        for text, expected in (
            ("envia no zap pra Maria oi tudo bem", ("Maria", "oi tudo bem")),
            ("chama o João no whatsapp e fala que eu cheguei", ("João", "eu cheguei")),
        ):
            sent.clear()
            agent.handle(text)
            self.assertEqual(sent, [expected], text)


class KnowledgeQuestionTests(unittest.TestCase):
    def test_questions_skip_the_planner(self) -> None:
        from brain.agent_loop import AgentLoop

        for text in ("me explique o que é um buraco negro", "o que é inflação", "quem foi Santos Dumont", "por que o céu é azul"):
            with self.subTest(text=text):
                self.assertTrue(AgentLoop._is_knowledge_question(text))
        for text in ("abra o chrome", "toque rock", "que horas são", "pesquise o que é inflação no youtube"):
            with self.subTest(text=text):
                self.assertFalse(AgentLoop._is_knowledge_question(text))


class StartupConfigTests(unittest.TestCase):
    def test_launcher_reloads_user_environment(self) -> None:
        script = (ROOT / "iniciar_duque.bat").read_text(encoding="utf-8")
        self.assertIn("GetEnvironmentVariables('User')", script)
        self.assertIn("DUQUE_*", script)
        self.assertIn("Duque.vbs", script)

    def test_toggle_scripts(self) -> None:
        self.assertIn("DUQUE_VOICE openai", (ROOT / "usar_openai.bat").read_text(encoding="utf-8"))
        self.assertIn("DUQUE_VOICE local", (ROOT / "usar_local.bat").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
