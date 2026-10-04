"""Grupos do WhatsApp, leitura de conversa e rascunhos por link (e-mail, agenda, compartilhar)."""

from __future__ import annotations

import unittest
import urllib.parse
from datetime import datetime
from typing import Any

from computer.compose_links import ComposeLinks
from computer.messaging import Messaging
from computer.whatsapp_flow import (
    TOOL_DOCS,
    WhatsAppDesktop,
    WhatsAppRequest,
    parse_delivery,
    parse_many,
    parse_request,
    split_group,
)


class GroupParsingTests(unittest.TestCase):
    def test_failing_sentences_from_the_field(self) -> None:
        delivery = parse_delivery("envie para o grupo Teste no WhatsApp")
        assert delivery is not None
        self.assertEqual((delivery.contact, delivery.group, delivery.text), ("Teste", True, ""))

        delivery = parse_delivery("mande no grupo Família do zap")
        assert delivery is not None
        self.assertEqual((delivery.contact, delivery.group), ("Família", True))

        request = parse_request("manda no grupo Teste dizendo oi")
        assert request is not None
        self.assertEqual((request.contact, request.text, request.group, request.send), ("Teste", "oi", True, True))

    def test_delivery_variants(self) -> None:
        cases = {
            "mande isso pro grupo Teste": "Teste",
            "envia o poema para o grupo Trabalho no whatsapp": "Trabalho",
            "mande no grupo Família do Zé": "Família do Zé",  # "do Zé" é parte do nome do grupo
            "manda o texto ao grupo Amigos pelo zap": "Amigos",
            "mande no grupo Futebol do whatsapp, sem ler pra mim": "Futebol",
        }
        for text, name in cases.items():
            with self.subTest(text=text):
                delivery = parse_delivery(text)
                assert delivery is not None
                self.assertEqual(delivery.contact, name)
                self.assertTrue(delivery.group)

    def test_conversation_is_not_forced_to_group(self) -> None:
        delivery = parse_delivery("mande isso na conversa Ana")
        assert delivery is not None
        self.assertEqual((delivery.contact, delivery.group), ("Ana", False))

    def test_request_variants(self) -> None:
        cases = {
            "manda uma mensagem pro grupo Trabalho dizendo que cheguei": ("Trabalho", "cheguei"),
            "envia no zap pro grupo Teste oi tudo bem": ("Teste", "oi tudo bem"),
            "manda no grupo Família do zap dizendo bom dia": ("Família", "bom dia"),
            "procure o grupo Teste e mande oi": ("Teste", "oi"),
            "chama o grupo Amigos no zap e fala que cheguei": ("Amigos", "cheguei"),
            "manda um oi pro grupo Teste": ("Teste", "oi"),
        }
        for text, (name, message) in cases.items():
            with self.subTest(text=text):
                request = parse_request(text)
                assert request is not None
                self.assertEqual((request.contact, request.text, request.group), (name, message, True))

    def test_people_unchanged(self) -> None:
        request = parse_request("manda uma mensagem pro João dizendo que vou atrasar")
        assert request is not None
        self.assertEqual((request.contact, request.text, request.group), ("João", "vou atrasar", False))
        request = parse_request("procure pelo Otávio que trabalha comigo na Embralan e encaminhe a mensagem reunião às 10")
        assert request is not None
        self.assertEqual((request.contact, request.hint, request.group), ("Otávio", "trabalha comigo na Embralan", False))
        delivery = parse_delivery("mande pro João no whatsapp web no perfil Embralan")
        assert delivery is not None
        self.assertEqual((delivery.contact, delivery.profile, delivery.group), ("João", "Embralan", False))
        self.assertIsNone(parse_delivery("manda pra Maria dizendo que cheguei"))

    def test_parse_many_with_group(self) -> None:
        jobs = parse_many("no perfil A mande para o grupo Teste e no perfil B mande para Maria, ambos dizendo oi")
        self.assertEqual([(job.contact, job.group) for job in jobs], [("Teste", True), ("Maria", False)])

    def test_request_positional_construction_still_works(self) -> None:
        request = WhatsAppRequest("Ana", "", "oi", True, "")
        self.assertFalse(request.group)

    def test_split_group(self) -> None:
        self.assertEqual(split_group("grupo Teste"), ("Teste", True))
        self.assertEqual(split_group("o grupo 'Família'"), ("Família", True))
        self.assertEqual(split_group("conversa do grupo Trabalho"), ("Trabalho", True))
        self.assertEqual(split_group("Maria"), ("Maria", False))
        self.assertEqual(split_group("Grupinho"), ("Grupinho", False))


class FakeKeys:
    def __init__(self) -> None:
        self.log: list[str] = []

    def press(self, key: str) -> None:
        self.log.append(f"press:{key}")

    def hotkey(self, *keys: str) -> None:
        self.log.append("hotkey:" + "+".join(keys))

    def type_text(self, text: str) -> None:
        self.log.append(f"type:{text}")


class GroupFlowTests(unittest.TestCase):
    def flow(self, answers: list[str], phone: str | None = "5519999999999") -> tuple[WhatsAppDesktop, FakeKeys, list[str], list[str]]:
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

    def test_group_searches_bare_name_and_never_uses_phone(self) -> None:
        flow, keys, opened, _ = self.flow(["Teste 🎉", "sim"])
        result = flow.whatsapp_send("grupo Teste", "um poema")  # o modelo mandou com o rótulo
        self.assertTrue(result["sent"])
        self.assertEqual(opened, ["app:whatsapp"])  # nada de whatsapp://send?phone=
        self.assertIn("type:Teste", keys.log)
        self.assertNotIn("type:grupo Teste", keys.log)

    def test_group_flag(self) -> None:
        flow, keys, opened, _ = self.flow(["Família do Zé", "sim"])
        result = flow.whatsapp_send("Família do Zé", "oi", group=True)
        self.assertTrue(result["sent"])
        self.assertEqual(opened, ["app:whatsapp"])

    def test_group_wrong_chat_types_nothing(self) -> None:
        flow, keys, _, _ = self.flow(["Carlos"])
        result = flow.whatsapp_send("Teste", "segredo", group=True)
        self.assertFalse(result["success"])
        self.assertFalse(any(entry == "type:segredo" for entry in keys.log))

    def test_group_without_vision_prepares_honestly(self) -> None:
        prepared: list[Any] = []
        flow = WhatsAppDesktop(
            open_app=lambda _n: None, open_target=lambda _u: None, keys=FakeKeys(), ask_screen=None,
            without_vision=lambda contact, text: prepared.append((contact, text)) or {"message": "Não tenho o número"},
        )
        result = flow.whatsapp_send("grupo Teste", "oi")
        self.assertEqual(prepared, [("Teste", "oi")])
        self.assertIn("grupo Teste", result["message"])
        self.assertNotIn("número", result["message"])

    def test_read_returns_last_messages_and_types_nothing_in_chat(self) -> None:
        flow, keys, opened, questions = self.flow(["Teste", "Ana: oi\nBeto: bom dia\nEu: olá"])
        result = flow.whatsapp_read("Teste", count=2, group=True)
        self.assertEqual(result["messages"], ["Beto: bom dia", "Eu: olá"])
        self.assertIn("Beto: bom dia", result["message"])
        self.assertEqual(keys.log, ["press:esc", "hotkey:ctrl+f", "type:Teste", "press:down", "press:enter"])
        self.assertIn("2", questions[-1])

    def test_read_person_with_phone_opens_link_without_text(self) -> None:
        flow, keys, opened, _ = self.flow(["Maria", "Maria: cheguei"])
        result = flow.whatsapp_read("Maria")
        self.assertEqual(opened, ["whatsapp://send?phone=5519999999999"])
        self.assertEqual(result["messages"], ["Maria: cheguei"])
        self.assertEqual(keys.log, [])

    def test_read_wrong_chat(self) -> None:
        flow, _, _, _ = self.flow(["Carlos"], phone=None)
        result = flow.whatsapp_read("Otávio")
        self.assertFalse(result["success"])

    def test_read_without_vision_is_honest(self) -> None:
        flow = WhatsAppDesktop(open_app=lambda _n: None, open_target=lambda _u: None, keys=FakeKeys(), ask_screen=None)
        result = flow.whatsapp_read("Teste", group=True)
        self.assertFalse(result["success"])
        self.assertIn("visão", result["error"])

    def test_tool_docs_mention_groups(self) -> None:
        for name in ("whatsapp_send", "whatsapp_message", "whatsapp_read"):
            description, required, types = TOOL_DOCS[name]
            self.assertIn("grupo", description)
            self.assertIn("group", types)
            self.assertTrue(set(required) <= set(types))


class FakeMemory:
    def __init__(self) -> None:
        self.data: dict[Any, Any] = {}

    def recall(self, layer: Any, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def remember(self, layer: Any, key: str, value: Any) -> None:
        self.data[key] = value


class MessagingGroupTests(unittest.TestCase):
    def test_group_message_opens_text_only(self) -> None:
        opened: list[str] = []
        messaging = Messaging(FakeMemory(), opened.append)  # type: ignore[arg-type]
        result = messaging.whatsapp_message("grupo Teste", "oi gente")
        self.assertEqual(opened, ["whatsapp://send?text=oi%20gente"])
        self.assertIn("grupo Teste", result["message"])
        self.assertTrue(result["group"])


class ComposeLinksTests(unittest.TestCase):
    def setUp(self) -> None:
        self.opened: list[str] = []
        self.tools = ComposeLinks(self.opened.append, now=lambda: datetime(2026, 10, 4, 10, 0))  # domingo

    @staticmethod
    def query(url: str) -> dict[str, str]:
        return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query, keep_blank_values=True))

    def test_gmail(self) -> None:
        result = self.tools.email_compose("ana@x.com", "Olá & até já", "Linha 1\nLinha 2 ção?")
        self.assertTrue(result["opened"])
        url = self.opened[0]
        self.assertTrue(url.startswith("https://mail.google.com/mail/?view=cm&fs=1&to=ana%40x.com&su="))
        self.assertNotIn(" ", url)
        self.assertNotIn("+", url)
        self.assertEqual(self.query(url)["su"], "Olá & até já")
        self.assertEqual(self.query(url)["body"], "Linha 1\nLinha 2 ção?")
        self.assertIn("pronto", result["message"])

    def test_outlook_and_mailto(self) -> None:
        self.tools.email_compose("a@b.com", "Oi", "corpo", provider="outlook")
        self.assertTrue(self.opened[0].startswith("https://outlook.live.com/mail/0/deeplink/compose?to=a%40b.com&subject=Oi&body=corpo"))
        self.tools.email_compose("a@b.com; c@d.com", "Assunto x", "y", provider="padrao")
        self.assertEqual(self.opened[1], "mailto:a@b.com,c@d.com?subject=Assunto%20x&body=y")

    def test_email_errors(self) -> None:
        self.assertFalse(self.tools.email_compose()["success"])
        self.assertFalse(self.tools.email_compose("a@b.com", provider="yahoo")["success"])
        self.assertEqual(self.opened, [])

    def test_calendar(self) -> None:
        result = self.tools.calendar_event("Reunião & café", "amanhã às 9h", 90, "sala 2")
        url = self.opened[0]
        self.assertTrue(url.startswith("https://calendar.google.com/calendar/render?action=TEMPLATE&"))
        query = self.query(url)
        self.assertEqual(query["dates"], "20261005T090000/20261005T103000")
        self.assertEqual(query["text"], "Reunião & café")
        self.assertEqual(query["details"], "sala 2")
        self.assertIn("20261005T090000/", url)  # a barra fica legível
        self.assertEqual(result["start"], "2026-10-05T09:00")

    def test_calendar_variants(self) -> None:
        self.tools.calendar_event("Jogo", "sexta 18:30")
        self.assertEqual(self.query(self.opened[-1])["dates"], "20261009T183000/20261009T193000")
        self.tools.calendar_event("Pausa", "daqui a 2 horas", duration_minutes=15)
        self.assertEqual(self.query(self.opened[-1])["dates"], "20261004T120000/20261004T121500")

    def test_calendar_errors(self) -> None:
        self.assertFalse(self.tools.calendar_event("", "amanhã")["success"])
        self.assertFalse(self.tools.calendar_event("Algo", "qualquer dia")["success"])
        self.assertEqual(self.opened, [])

    def test_share(self) -> None:
        text = "Poema: rosa & sol"
        self.tools.share_text(text, "whatsapp")
        self.tools.share_text(text, "email")
        self.tools.share_text(text, "telegram")
        self.tools.share_text(text, "X")
        encoded = "Poema%3A%20rosa%20%26%20sol"
        self.assertEqual(self.opened, [
            f"https://wa.me/?text={encoded}",
            f"mailto:?body={encoded}",
            f"https://t.me/share/url?url=&text={encoded}",
            f"https://twitter.com/intent/tweet?text={encoded}",
        ])
        self.assertFalse(self.tools.share_text(text, "orkut")["success"])
        self.assertFalse(self.tools.share_text("  ", "whatsapp")["success"])

    def test_open_failure_is_reported(self) -> None:
        def boom(_url: str) -> None:
            raise OSError("sem navegador")

        result = ComposeLinks(boom).share_text("oi", "whatsapp")
        self.assertFalse(result["success"])

    def test_contract(self) -> None:
        class Executor:
            def __init__(self) -> None:
                self.tools: dict[str, Any] = {}

            def register(self, name: str, tool: Any) -> None:
                self.tools[name] = tool

        executor = Executor()
        self.tools.register(executor)
        names = [spec[0] for spec in ComposeLinks.SPECS]
        self.assertEqual(sorted(executor.tools), sorted(names))
        self.assertEqual(set(ComposeLinks.RISK), set(names))
        self.assertTrue(all(level == "low" for level in ComposeLinks.RISK.values()))


if __name__ == "__main__":
    unittest.main()
