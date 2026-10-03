"""Ajustes 9: um nome só, ouvido aberto após a saudação, YouTube que abre de verdade e WhatsApp completo."""

from __future__ import annotations

import json
import unittest
from typing import Any

from brain.compound import plan_steps
from brain.planner import Planner
from brain.router import IntentRouter
from computer.assistant_tools import AssistantTools
from computer.chrome import find_profile
from computer.whatsapp_flow import WhatsAppDesktop, parse_request
from computer.windows_focus import wait_for_window
from voice.gate import ListenGate, addressed, is_echo


class OneNameTests(unittest.TestCase):
    def test_only_telex(self) -> None:
        self.assertTrue(addressed("Telex, abre o YouTube"))
        for other in ("Duque, abre o YouTube", "Hey Jarvis", "Jarvis, que horas são"):
            self.assertFalse(addressed(other), other)


class GreetingEarTests(unittest.TestCase):
    def test_echo_of_own_voice_does_not_close_the_ear(self) -> None:
        """Regressão: a saudação voltava pelo microfone e fechava o ouvido."""
        gate = ListenGate()
        gate.open(45)
        self.assertEqual(gate.decide("Boa tarde, Du. Tudo pronto por aqui.", speaking=True).action, "ignore")
        self.assertTrue(gate.is_open)
        self.assertEqual(gate.decide("abre o youtube").action, "respond")  # sem repetir "TELEX"

    def test_name_still_interrupts_while_speaking(self) -> None:
        gate = ListenGate()
        self.assertEqual(gate.decide("Telex, stop", speaking=True).action, "stop")

    def test_echo_detection(self) -> None:
        spoken = "Boa tarde, Du. Tudo pronto por aqui, em que posso ajudar?"
        self.assertTrue(is_echo("boa tarde du tudo pronto por aqui", spoken))
        self.assertFalse(is_echo("abre o youtube e toca lofi", spoken))
        self.assertFalse(is_echo("ok", spoken))


class ChromeTests(unittest.TestCase):
    STATE = {"profile": {"last_used": "Default", "info_cache": {"Default": {"name": "Pessoa 1"}}}}

    def test_strict_profile_does_not_fall_back(self) -> None:
        self.assertEqual(find_profile(self.STATE, "zaninieduardo0"), "Default")
        self.assertIsNone(find_profile(self.STATE, "zaninieduardo0", strict=True))

    def test_wait_for_window(self) -> None:
        calls: list[float] = []
        titles = iter([["Nova guia"], ["Nova guia"], ["YouTube - Google Chrome"]])
        self.assertTrue(wait_for_window("youtube", 5, titles=lambda: next(titles), sleep=calls.append, step=0.4))
        self.assertEqual(len(calls), 2)
        self.assertFalse(wait_for_window("youtube", 0.8, titles=lambda: ["Gmail"], sleep=lambda _s: None, step=0.4))

    def test_youtube_play_reports_when_page_never_appears(self) -> None:
        opened: list[str] = []
        tools = AssistantTools(
            fetch_text=lambda _u: '"videoId":"kXYiU_JCYtU"', open_target=opened.append,
            wait_window=lambda _f, _t: False,
        )
        result = tools.youtube_play("numb")
        self.assertFalse(result["playing"])
        self.assertIn("não vi a página abrir", result["message"])


class WhatsAppParseTests(unittest.TestCase):
    def test_du_example(self) -> None:
        request = parse_request(
            "TELEX, abra o whatsapp, procure pelo Otávio que trabalha comigo na Embralan, e encaminhe a mensagem Reunião amanhã às 9h"
        )
        assert request is not None
        self.assertEqual((request.contact, request.hint, request.text, request.send),
                         ("Otávio", "trabalha comigo na Embralan", "Reunião amanhã às 9h", True))

    def test_other_forms(self) -> None:
        cases = {
            "manda uma mensagem pro João no whatsapp dizendo que vou atrasar": ("João", "", "vou atrasar", True),
            "mande no whatsapp para a Ana: chego em 10 minutos": ("Ana", "", "chego em 10 minutos", True),
            "procura a Maria da Embralan no whatsapp e escreve: oi, tudo bem?": ("Maria", "Embralan", "oi, tudo bem?", False),
            'abra o whatsapp, procure o Otávio e mande "bom dia"': ("Otávio", "", "bom dia", True),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                request = parse_request(text)
                assert request is not None
                self.assertEqual((request.contact, request.hint, request.text, request.send), expected)

    def test_not_a_message(self) -> None:
        self.assertIsNone(parse_request("que horas são"))

    def test_whole_request_is_one_step_and_one_tool(self) -> None:
        text = "TELEX, abra o whatsapp, procure pelo Otávio que trabalha comigo na Embralan, e encaminhe a mensagem Reunião amanhã"
        steps = plan_steps(text)
        self.assertEqual(len(steps), 1)
        route = IntentRouter().route(steps[0])
        plan = Planner().build(steps[0], route.intent.value)
        self.assertEqual(plan.steps[0].tool, "whatsapp_send")
        self.assertEqual(plan.steps[0].arguments["contact"], "Otávio")


class FakeKeys:
    def __init__(self) -> None:
        self.log: list[str] = []

    def press(self, key: str) -> None:
        self.log.append(f"press:{key}")

    def hotkey(self, *keys: str) -> None:
        self.log.append("hotkey:" + "+".join(keys))

    def type_text(self, text: str) -> None:
        self.log.append(f"type:{text}")


class WhatsAppFlowTests(unittest.TestCase):
    def flow(self, answers: list[str], phone: str | None = None) -> tuple[WhatsAppDesktop, FakeKeys, list[str], list[str]]:
        keys, opened, questions = FakeKeys(), [], []
        replies = iter(answers)

        def ask(question: str) -> str:
            questions.append(question)
            return next(replies)

        flow = WhatsAppDesktop(
            open_app=lambda name: opened.append(f"app:{name}"),
            open_target=lambda url: opened.append(url),
            keys=keys, ask_screen=ask, phone_of=lambda _n: phone, sleep=lambda _s: None,
        )
        return flow, keys, opened, questions

    def test_search_choose_verify_type_send(self) -> None:
        flow, keys, opened, questions = self.flow(["2", "Otávio Embralan", "sim"])
        result = flow.whatsapp_send("Otávio", "Reunião amanhã", hint="trabalha comigo na Embralan")
        self.assertTrue(result["sent"])
        self.assertEqual(opened, ["app:whatsapp"])
        self.assertEqual(keys.log, [
            "press:esc", "hotkey:ctrl+f", "type:Otávio", "press:down", "press:down", "press:enter",
            "type:Reunião amanhã", "press:enter",
        ])
        self.assertIn("Embralan", questions[0])

    def test_wrong_chat_types_nothing(self) -> None:
        flow, keys, _, _ = self.flow(["Carlos Silva"])
        result = flow.whatsapp_send("Otávio", "segredo")
        self.assertFalse(result["success"])
        self.assertIn("Não escrevi nada", result["error"])
        self.assertFalse(any(entry.startswith("type:segredo") for entry in keys.log))

    def test_write_only_does_not_send(self) -> None:
        flow, keys, _, _ = self.flow(["Maria"])
        result = flow.whatsapp_send("Maria", "oi", send=False)
        self.assertFalse(result["sent"])
        self.assertEqual(keys.log[-1], "type:oi")

    def test_saved_contact_opens_link(self) -> None:
        flow, keys, opened, _ = self.flow(["João", "sim"], phone="5519998765432")
        result = flow.whatsapp_send("João", "vou atrasar")
        self.assertTrue(result["sent"])
        self.assertTrue(opened[0].startswith("whatsapp://send?phone=5519998765432&text=vou%20atrasar"))
        self.assertEqual(keys.log, ["press:enter"])  # o texto já vem no link

    def test_not_confirmed_on_screen(self) -> None:
        flow, _, _, _ = self.flow(["Otávio", "não"])
        result = flow.whatsapp_send("Otávio", "oi")
        self.assertIsNone(result["sent"])
        self.assertIn("Confere", result["message"])

    def test_without_vision_only_prepares(self) -> None:
        prepared: list[Any] = []
        flow = WhatsAppDesktop(
            open_app=lambda _n: None, open_target=lambda _u: None, keys=FakeKeys(), ask_screen=None,
            without_vision=lambda contact, text: prepared.append((contact, text)) or {"message": "pronta"},
        )
        self.assertEqual(flow.whatsapp_send("Ana", "oi"), {"message": "pronta"})
        self.assertEqual(prepared, [("Ana", "oi")])
        json.dumps(prepared)


if __name__ == "__main__":
    unittest.main()
