"""Núcleo novo do TELEX: laço de ferramentas, WhatsApp Web e navegador."""

from __future__ import annotations

import functools
import http.server
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

from telex import browser as web
from telex import whatsapp
from telex.agent import TelexAgent
from telex.browser import Browser, normalize_url
from telex.llm import ClaudeBrain, OpenAIBrain, Reply, Tool, ToolOutput, provider_name

HERE = Path(__file__).resolve().parent


class MatchingTests(unittest.TestCase):
    def test_best_match_prefers_exact_then_prefix_and_ignores_accents(self) -> None:
        titles = ["João Silva", "Joana", "Grupo Teste", "Família Zanini"]
        self.assertEqual(whatsapp.best_match("joao", titles), "João Silva")
        self.assertEqual(whatsapp.best_match("Joana", titles), "Joana")
        self.assertEqual(whatsapp.best_match("grupo teste", titles), "Grupo Teste")
        self.assertEqual(whatsapp.best_match("familia", titles), "Família Zanini")
        self.assertIsNone(whatsapp.best_match("Pedro", titles))

    def test_normalize_url(self) -> None:
        self.assertEqual(normalize_url("youtube.com"), "https://youtube.com")
        self.assertEqual(normalize_url("https://g1.globo.com/x"), "https://g1.globo.com/x")
        self.assertTrue(normalize_url("previsão do tempo").startswith("https://www.google.com/search?q="))
        with self.assertRaises(ValueError):
            normalize_url("file:///C:/Windows")


class FakeBrain:
    """Simula a IA: chama as ferramentas indicadas e devolve um texto."""

    def __init__(self, calls: list[tuple[str, dict[str, Any]]], answer: str = "Feito, Du.") -> None:
        self.calls = calls
        self.answer = answer
        self.outputs: list[ToolOutput] = []
        self.seen: list[str] = []

    def run(self, system: str, history: Any, text: str, tools: list[Tool], runner: Any) -> Reply:
        self.seen.append(text)
        reply = Reply(self.answer)
        for name, arguments in self.calls:
            self.outputs.append(runner(name, arguments))
            reply.tools_used.append(name)
            reply.steps += 1
        return reply


class AgentTests(unittest.TestCase):
    def test_whatsapp_goes_to_the_web_never_to_the_desktop_app(self) -> None:
        agent = TelexAgent(brain=FakeBrain([("abrir_programa", {"nome": "WhatsApp"})]), browser=mock.Mock())
        agent.browser.call.return_value = {"titulo": "WhatsApp", "url": whatsapp.URL}
        with mock.patch("computer.tools.ComputerTools.open_app") as desktop:
            reply = agent.handle("abre o WhatsApp")
        desktop.assert_not_called()
        agent.browser.call.assert_called_once()
        self.assertEqual(reply.text, "Feito, Du.")

    def test_tool_errors_are_reported_back_to_the_model(self) -> None:
        brain = FakeBrain([("whatsapp_enviar", {"contato": "x", "mensagem": "oi"}), ("nao_existe", {}), ("ler_arquivo", {})])
        agent = TelexAgent(brain=brain, browser=mock.Mock())
        agent.browser.call.side_effect = RuntimeError("WhatsApp fora do ar")
        agent.handle("manda oi pro x")
        self.assertTrue(all(output.is_error for output in brain.outputs))
        self.assertIn("WhatsApp fora do ar", brain.outputs[0].text)
        self.assertIn("desconhecida", brain.outputs[1].text)
        self.assertIn("Argumentos inválidos", brain.outputs[2].text)

    def test_legacy_tools_are_reused(self) -> None:
        reminder = mock.Mock(return_value={"message": "Lembrete criado."})
        brain = FakeBrain([("lembrete", {"quando": "amanhã às 9h", "texto": "dentista"})])
        agent = TelexAgent(brain=brain, browser=mock.Mock(), legacy_tools={"reminder_at": reminder}.get)
        agent.handle("me lembra do dentista amanhã às 9h")
        reminder.assert_called_once_with(when="amanhã às 9h", text="dentista")
        self.assertFalse(brain.outputs[0].is_error)

    def test_notepad_writes_a_file(self) -> None:
        with tempfile.TemporaryDirectory() as folder, mock.patch("computer.file_tools.known_folder", return_value=Path(folder)):
            brain = FakeBrain([("bloco_de_notas", {"texto": "Rosas são vermelhas\nTELEX é legal", "titulo": "poema"})])
            TelexAgent(brain=brain, browser=mock.Mock()).handle("escreve um poema no bloco de notas")
            files = list((Path(folder) / "TELEX").glob("poema*.txt"))
            self.assertEqual(len(files), 1)
            self.assertIn("TELEX é legal", files[0].read_text(encoding="utf-8"))

    def test_history_is_kept_short_and_time_goes_with_the_request(self) -> None:
        brain = FakeBrain([])
        agent = TelexAgent(brain=brain, browser=mock.Mock(), history_size=2)
        for index in range(4):
            agent.handle(f"pedido {index}")
        self.assertEqual([question for question, _ in agent.history], ["pedido 2", "pedido 3"])
        self.assertIn("(Agora:", brain.seen[-1])

    def test_brain_failure_becomes_a_spoken_error(self) -> None:
        brain = mock.Mock()
        brain.run.side_effect = ConnectionError("sem internet")
        reply = TelexAgent(brain=brain, browser=mock.Mock()).handle("oi")
        self.assertTrue(reply.failed)
        self.assertIn("ConnectionError", reply.text)


def _block(kind: str, **fields: Any) -> SimpleNamespace:
    return SimpleNamespace(type=kind, **fields)


class ClaudeLoopTests(unittest.TestCase):
    def test_runs_tools_until_the_final_answer(self) -> None:
        responses = [
            SimpleNamespace(stop_reason="tool_use", content=[_block("tool_use", id="t1", name="abrir_site", input={"endereco": "g1.com"})]),
            SimpleNamespace(stop_reason="end_turn", content=[_block("text", text="Abri o G1.")]),
        ]
        client = mock.Mock()
        client.beta.messages.create.side_effect = responses
        runner = mock.Mock(return_value=ToolOutput('{"ok": true}'))
        reply = ClaudeBrain(client=client).run("sistema", [("oi", "olá")], "abre o g1", [Tool("abrir_site", "x", {"endereco": {"type": "string"}}, ("endereco",))], runner)
        self.assertEqual(reply.text, "Abri o G1.")
        runner.assert_called_once_with("abrir_site", {"endereco": "g1.com"})
        second = client.beta.messages.create.call_args_list[1].kwargs
        self.assertEqual(second["fallbacks"], "default")
        self.assertEqual(second["messages"][0], {"role": "user", "content": "oi"})
        self.assertEqual(second["messages"][4]["content"][0]["tool_use_id"], "t1")  # a lista é a mesma (só cresce)

    def test_refusal_is_not_read_as_content(self) -> None:
        client = mock.Mock()
        client.beta.messages.create.return_value = SimpleNamespace(stop_reason="refusal", content=[])
        reply = ClaudeBrain(client=client).run("s", [], "x", [], mock.Mock())
        self.assertTrue(reply.failed)


class OpenAILoopTests(unittest.TestCase):
    def test_runs_tools_until_the_final_answer(self) -> None:
        call = SimpleNamespace(id="c1", function=SimpleNamespace(name="pesquisar_google", arguments='{"pesquisa": "clima"}'))
        first = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[call]))])
        final = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Pesquisei.", tool_calls=None))])
        client = mock.Mock()
        client.chat.completions.create.side_effect = [first, final]
        runner = mock.Mock(return_value=ToolOutput("ok", image_png=b"png"))
        reply = OpenAIBrain(client=client).run("s", [], "pesquisa clima", [Tool("pesquisar_google", "x")], runner)
        self.assertEqual(reply.text, "Pesquisei.")
        messages = client.chat.completions.create.call_args_list[1].kwargs["messages"]
        self.assertEqual(messages[-2]["role"], "tool")
        self.assertEqual(messages[-1]["role"], "user")  # a imagem vai numa mensagem do usuário

    def test_provider_choice(self) -> None:
        with mock.patch.dict("os.environ", {"TELEX_IA": "", "ANTHROPIC_API_KEY": "x"}):
            self.assertEqual(provider_name(), "claude")
        with mock.patch.dict("os.environ", {"TELEX_IA": "openai", "ANTHROPIC_API_KEY": "x"}):
            self.assertEqual(provider_name(), "openai")


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args: Any) -> None:
        pass


class BrowserFlowTests(unittest.TestCase):
    """Com um navegador de verdade (headless) e um WhatsApp Web falso servido localmente."""

    browser: Browser
    server: http.server.ThreadingHTTPServer
    temp: tempfile.TemporaryDirectory

    @classmethod
    def setUpClass(cls) -> None:
        handler = functools.partial(_QuietHandler, directory=str(HERE))
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.temp = tempfile.TemporaryDirectory()
        cls.browser = Browser(Path(cls.temp.name) / "perfil", headless=True)
        try:
            cls.browser.call(lambda b: b.context(), timeout=90)
        except Exception as exc:  # sem navegador instalado
            cls.tearDownClass()
            raise unittest.SkipTest(f"navegador indisponível: {exc}")
        base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.url = base + "/fake_whatsapp.html"
        cls.patch = mock.patch.multiple(whatsapp, URL=cls.url, HOST="127.0.0.1")
        cls.patch.start()

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "patch"):
            cls.patch.stop()
        cls.browser.close()
        cls.server.shutdown()
        cls.temp.cleanup()

    def test_open_chat_uses_whatsapp_search(self) -> None:
        result = self.browser.call(whatsapp.open_chat, "joao")
        self.assertEqual(result, {"ok": True, "conversa": "João Silva"})

    def test_unknown_contact_lists_what_appeared(self) -> None:
        result = self.browser.call(whatsapp.open_chat, "Pedro")
        self.assertFalse(result["ok"])
        self.assertIn("Pedro", result["erro"])

    def test_send_to_group_and_confirm(self) -> None:
        poem = "Rosas são vermelhas\nO TELEX funciona"
        result = self.browser.call(whatsapp.send_message, "Grupo Teste", poem)
        self.assertTrue(result["ok"], result)
        messages = self.browser.call(whatsapp.read_messages, "Grupo Teste", 5)
        self.assertIn("O TELEX funciona", messages["mensagens"][-1])

    def test_read_messages_and_recent_chats(self) -> None:
        messages = self.browser.call(whatsapp.read_messages, "João Silva", 5)
        self.assertEqual(messages["mensagens"], ["[09:10, 07/10/2026] João Silva: Bom dia!"])
        chats = self.browser.call(whatsapp.recent_chats, 10)
        self.assertTrue(any("Joana" in row for row in chats["conversas"]))

    def test_generic_page_tools(self) -> None:
        opened = self.browser.call(web.open_site, self.url)
        self.assertTrue(opened["ok"])
        elements = self.browser.call(web.list_elements)["elementos"]
        search = next(item for item in elements if "Pesquisar" in item)
        number = int(search.split(" ", 1)[0])
        self.browser.call(web.type_into, number, "Joana", False)
        self.browser.call(lambda b: b.page.wait_for_timeout(400))
        text = self.browser.call(web.read_page)["texto"]
        self.assertIn("Joana", text)
        self.assertNotIn("João Silva", text)


class ServerUsesNewCoreTests(unittest.TestCase):
    def test_command_and_voice_go_through_the_new_core(self) -> None:
        import servidor

        fake = TelexAgent(brain=FakeBrain([], answer="Mandei no grupo, Du."), browser=mock.Mock())
        with mock.patch.object(servidor, "NUCLEO_NOVO", True), mock.patch.object(servidor, "_telex", fake), \
                mock.patch.object(servidor.agent, "handle", side_effect=AssertionError("núcleo antigo chamado")):
            data = servidor.app.test_client().post("/api/comando", json={"text": "manda um oi no grupo Teste"}).get_json()
            spoken = servidor._execute_for_voice("lê as mensagens do João")
        self.assertEqual(data["text"], "Mandei no grupo, Du.")
        self.assertTrue(data["execution"]["success"])
        self.assertEqual(spoken, "Mandei no grupo, Du.")


if __name__ == "__main__":
    unittest.main()
