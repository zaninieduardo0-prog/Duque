"""Fluxos de autonomia de ponta a ponta: o texto criado numa etapa chega ao destino pedido."""

from __future__ import annotations

from typing import Any

from tests.test_ajustes_20 import POEM, PoemToWhatsAppTests


class GroupAndCarryTests(PoemToWhatsAppTests):
    def make_group_agent(self) -> tuple[Any, list[tuple[Any, ...]]]:
        agent, _model, _sent = self.make_agent()
        sent: list[tuple[Any, ...]] = []
        agent.executor.register(
            "whatsapp_send",
            lambda contact, text, hint="", send=True, profile="", group=False: sent.append((contact, text, group))
            or {"message": f"Mensagem enviada para {contact}."},
        )
        return agent, sent

    def test_poem_in_notepad_then_whatsapp_group(self) -> None:
        # O pedido exato que falhou no teste do Du.
        agent, sent = self.make_group_agent()
        result = agent.handle("escreva um poema no bloco de notas e envie para o grupo Teste no WhatsApp")
        self.assertEqual(sent, [("Teste", POEM, True)])
        self.assertNotIn("ferramenta", result.text.casefold())
        self.assertTrue(list((self.tmp / "notas").glob("*.txt")))

    def test_message_to_group_with_text(self) -> None:
        agent, sent = self.make_group_agent()
        agent.handle("manda no grupo Teste dizendo oi")
        self.assertEqual(sent, [("Teste", "oi", True)])

    def test_poem_goes_to_clipboard(self) -> None:
        agent, _model, _sent = self.make_agent()
        copied: list[str] = []
        agent.executor.register("clipboard_write", lambda text: copied.append(text) or {"message": "Copiado."})
        agent.handle("crie um poema sobre o mar e copie isso")
        self.assertEqual(copied, [POEM])

    def test_poem_goes_to_email_draft(self) -> None:
        agent, _model, _sent = self.make_agent()
        drafts: list[dict[str, Any]] = []
        agent.executor.register("email_compose", lambda **kwargs: drafts.append(kwargs) or {"message": "Rascunho pronto."})
        agent.handle("crie um poema sobre o mar e mande por e-mail para ana@exemplo.com")
        self.assertEqual(drafts, [{"to": "ana@exemplo.com", "body": POEM}])

    def test_poem_goes_to_file(self) -> None:
        agent, _model, _sent = self.make_agent()
        saved: list[dict[str, Any]] = []
        agent.executor.register("save_text_file", lambda **kwargs: saved.append(kwargs) or {"message": "Salvo."})
        agent.handle("crie um poema sobre o mar e salve num arquivo chamado mar")
        self.assertEqual(saved, [{"name": "mar", "content": POEM}])

    def test_new_tools_are_visible_to_the_model(self) -> None:
        agent, _sent = self.make_group_agent()
        names = set(agent.schemas.names())
        for tool in (
            "whatsapp_read", "email_compose", "calendar_event", "read_webpage", "download_file",
            "windows_list", "window_focus", "open_settings", "save_text_file", "apps_list",
        ):
            self.assertIn(tool, names)
        self.assertTrue(agent.executor.security.assess("move_to_trash").confirmation_required)


del PoemToWhatsAppTests  # só a base; os testes dela já rodam no próprio arquivo
