"""Ajustes 20: pedidos que passam o resultado de uma etapa para a outra ("crie um poema e mande para o João")."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from brain.compound import plan_steps
from brain.model import ModelAdapter, ModelResponse
from computer.notepad import NotepadWriter
from computer.whatsapp_flow import parse_delivery, parse_request
from tests.helpers import TempDirTestCase

POEM = "O mar acorda devagar\nE beija a areia sem pressa."


class PoemModel(ModelAdapter):
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def respond(self, messages: list[dict[str, str]], **kwargs: Any) -> ModelResponse:
        self.prompts.append(messages[-1]["content"])
        return ModelResponse(POEM)


class DeliveryParseTests(unittest.TestCase):
    def test_delivery_without_text(self) -> None:
        cases = {
            "mande pro contato Maria no whatsapp web": ("Maria", "atual"),
            "manda isso pra Maria no zap": ("Maria", ""),
            "envie o poema para o João no whatsapp web, sem ler pra mim": ("João", "atual"),
            "mande ele pro Pedro da Embralan no whatsapp": ("Pedro", ""),
            "manda pra minha mãe no whatsapp web não precisa ler": ("mãe", "atual"),
        }
        for text, (contact, profile) in cases.items():
            with self.subTest(text=text):
                delivery = parse_delivery(text)
                assert delivery is not None
                self.assertEqual((delivery.contact, delivery.profile, delivery.text), (contact, profile, ""))

    def test_explicit_profile_wins(self) -> None:
        delivery = parse_delivery("mande pro João no whatsapp web no perfil Embralan")
        assert delivery is not None
        self.assertEqual(delivery.profile, "Embralan")

    def test_message_with_text_is_not_a_delivery(self) -> None:
        self.assertIsNotNone(parse_request("manda pra Maria no zap dizendo oi"))
        self.assertIsNone(parse_delivery("manda pra Maria dizendo que cheguei"))

    def test_other_requests_are_not_deliveries(self) -> None:
        for text in ("abra o chrome", "toque rock no youtube", "salve isso no bloco de notas"):
            self.assertIsNone(parse_delivery(text), text)


class NotepadCarryTests(unittest.TestCase):
    def test_literal_text_is_not_recomposed_and_is_returned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            writer = NotepadWriter(lambda _p: "NÃO DEVIA SER USADO", folder=Path(tmp), opener=lambda _p: None)
            result = writer.notepad_write("O texto do poema que já existe\nem duas linhas", literal=True)
            self.assertFalse(result["composed"])
            self.assertEqual(result["text"], "O texto do poema que já existe\nem duas linhas")

    def test_composed_text_is_returned_for_the_next_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            writer = NotepadWriter(lambda _p: POEM, folder=Path(tmp), opener=lambda _p: None)
            self.assertEqual(writer.notepad_write("um poema sobre o mar")["text"], POEM)


class PoemToWhatsAppTests(TempDirTestCase):
    def make_agent(self) -> tuple[Any, PoemModel, list[tuple[Any, ...]]]:
        from brain.agent_loop import AgentLoop
        from computer.workspace import Workspace
        from memory.memory import Memory

        model = PoemModel()
        with mock.patch.dict(os.environ, {"DUQUE_FORGE": "0"}):
            agent = AgentLoop(tasks=self.tasks, workspace=Workspace(self.tmp / "ws"), model=model, memory=Memory(self.database))
        self.addCleanup(agent.scheduled_runner.stop)
        writer = NotepadWriter(agent._compose_text, folder=self.tmp / "notas", opener=lambda _p: None)
        agent.executor.register("notepad_write", writer.notepad_write)
        sent: list[tuple[Any, ...]] = []
        agent.executor.register(
            "whatsapp_send",
            lambda contact, text, hint="", send=True, profile="": sent.append((contact, text, profile)) or {"message": f"Mensagem enviada para {contact}."},
        )
        return agent, model, sent

    def test_poem_in_notepad_then_whatsapp_web(self) -> None:
        agent, model, sent = self.make_agent()
        result = agent.handle("crie um poema no bloco de notas e mande pro contato Maria no whatsapp web")
        self.assertEqual(sent, [("Maria", POEM, "atual")])
        self.assertEqual(len(model.prompts), 1)  # o poema é criado uma vez só
        self.assertNotIn("acorda devagar", result.text)  # nunca lido em voz alta
        self.assertIn("Mensagem enviada para Maria", result.text)
        self.assertTrue(list((self.tmp / "notas").glob("*.txt")))

    def test_poem_without_notepad_goes_straight_to_the_contact(self) -> None:
        agent, model, sent = self.make_agent()
        result = agent.handle("crie um poema sobre o mar e mande pra Ana no zap, sem ler pra mim")
        self.assertEqual(sent, [("Ana", POEM, "")])
        self.assertNotIn("acorda devagar", result.text)

    def test_create_save_and_send(self) -> None:
        agent, _model, sent = self.make_agent()
        result = agent.handle("faça um poema sobre o mar, salve no bloco de notas e mande pra Ana no zap")
        self.assertEqual(sent, [("Ana", POEM, "")])
        self.assertTrue(list((self.tmp / "notas").glob("*.txt")))
        self.assertNotIn("acorda devagar", result.text)

    def test_without_text_to_send_it_says_so(self) -> None:
        agent, _model, sent = self.make_agent()
        result = agent.handle("mande pro contato Maria no whatsapp web")
        self.assertEqual(sent, [])  # nada é enviado às cegas
        self.assertTrue(result.text)

    def test_plain_message_still_works(self) -> None:
        agent, _model, sent = self.make_agent()
        agent.handle("manda um oi pra Maria no zap")
        self.assertEqual(sent, [("Maria", "oi", "")])

    def test_steps_are_split_as_expected(self) -> None:
        self.assertEqual(
            plan_steps("crie um poema no bloco de notas e mande pro contato Maria no whatsapp web"),
            ["crie um poema no bloco de notas", "mande pro contato Maria no whatsapp web"],
        )


if __name__ == "__main__":
    unittest.main()
