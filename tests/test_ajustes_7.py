"""Ajustes 7: pedidos em várias etapas, YouTube tocando de verdade, Bloco de Notas, voz e HUD."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any

from brain.compound import plan_steps
from brain.planner import Planner
from brain.router import IntentRouter
from computer.assistant_tools import AssistantTools, first_video_id
from computer.notepad import NotepadWriter, needs_composing, slug
from tests.helpers import TempDirTestCase


class CompoundStepsTests(unittest.TestCase):
    def test_open_app_plus_action_becomes_one_step(self) -> None:
        cases = {
            "Telex, abra o youtube e reproduza Numb do Linkin Park": ["toque Numb do Linkin Park no youtube"],
            "abre o youtube e toca lofi lá": ["toque lofi no youtube"],
            "abra o youtube e depois pesquise receitas de bolo": ["pesquise receitas de bolo no youtube"],
            "abra o bloco de notas e escreva um poema sobre o mar e o céu": ["escreva no bloco de notas: um poema sobre o mar e o céu"],
            "abre o bloco de notas e digita: lista de compras, arroz e feijão": ["escreva no bloco de notas: lista de compras, arroz e feijão"],
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(plan_steps(text), expected)

    def test_independent_actions_are_split(self) -> None:
        self.assertEqual(
            plan_steps("abra o spotify, aumente o volume e anote que preciso pagar a luz"),
            ["abra o spotify", "aumente o volume", "anote que preciso pagar a luz"],
        )
        self.assertEqual(plan_steps("abra o chrome e pesquise o preço do dólar"), ["abra o chrome", "pesquise o preço do dólar"])

    def test_content_is_never_split(self) -> None:
        for text in (
            "escreva um poema sobre amor e paixão",
            "toque rock e pop no youtube",
            "anote que preciso abrir a loja e fechar o caixa",
            "me lembra de abrir o forno e desligar o gás",
            "manda uma mensagem pro João dizendo que vou abrir e fechar",
            "crie a rotina noite: abre o youtube, diminua o volume",
            "analise o projeto e corrija os problemas",
            "escreva no bloco de notas: abra a janela e feche a porta",
            'digite "abra e feche"',
            "que horas são?",
        ):
            with self.subTest(text=text):
                self.assertEqual(len(plan_steps(text)), 1)


class PlanningTests(unittest.TestCase):
    def plan(self, text: str) -> list[tuple[str | None, dict[str, Any]]]:
        route = IntentRouter().route(text)
        return [(step.tool, step.arguments) for step in Planner().build(text, route.intent.value).steps]

    def test_play_vs_search_on_youtube(self) -> None:
        self.assertEqual(self.plan("toque Numb do Linkin Park no youtube"), [("youtube_play", {"query": "Numb do Linkin Park"})])
        self.assertEqual(self.plan("reproduza a trilha de interestelar no youtube"), [("youtube_play", {"query": "trilha de interestelar"})])
        self.assertEqual(self.plan("pesquise receitas no youtube"), [("youtube", {"query": "receitas"})])

    def test_notepad(self) -> None:
        self.assertEqual(self.plan("escreva no bloco de notas: um poema sobre o mar"), [("notepad_write", {"request": "um poema sobre o mar"})])
        self.assertEqual(self.plan("escreva um poema sobre o mar no bloco de notas"), [("notepad_write", {"request": "um poema sobre o mar"})])


class YouTubePlayTests(unittest.TestCase):
    def tools(self, html: str | Exception) -> tuple[AssistantTools, list[str]]:
        opened: list[str] = []

        def fetch(_url: str) -> str:
            if isinstance(html, Exception):
                raise html
            return html

        return AssistantTools(fetch_text=fetch, open_target=opened.append, wait_window=lambda _f, _t: True, reuse_window=lambda _f, _u: False), opened

    def test_plays_first_video(self) -> None:
        html = 'xx "videoId":"kXYiU_JCYtU" yy "videoId":"eVTXPUF4Oz4"'
        self.assertEqual(first_video_id(html), "kXYiU_JCYtU")
        tools, opened = self.tools(html)
        result = tools.youtube_play("numb linkin park")
        self.assertTrue(result["playing"])
        self.assertEqual(opened, ["https://www.youtube.com/watch?v=kXYiU_JCYtU&autoplay=1"])

    def test_falls_back_to_search_page(self) -> None:
        for page in ("<html>nada aqui</html>", OSError("sem internet")):
            with self.subTest(page=str(page)):
                tools, opened = self.tools(page)
                result = tools.youtube_play("lofi")
                self.assertFalse(result["playing"])
                self.assertIn("results?search_query=lofi", opened[0])


class NotepadTests(unittest.TestCase):
    def writer(self, folder: Path, compose: Any = None) -> tuple[NotepadWriter, list[Path]]:
        opened: list[Path] = []
        clock = lambda: datetime(2026, 10, 3, 14, 42, 10)  # noqa: E731
        return NotepadWriter(compose, folder=folder, opener=opened.append, clock=clock), opened

    def test_composes_poem_and_verifies_file(self) -> None:
        prompts: list[str] = []

        def compose(prompt: str) -> str:
            prompts.append(prompt)
            return "O mar canta baixo\nnas noites de estrela."

        with tempfile.TemporaryDirectory() as tmp:
            writer, opened = self.writer(Path(tmp), compose)
            result = writer.notepad_write("um poema sobre o mar")
            self.assertTrue(result["composed"])
            path = Path(result["path"])
            self.assertEqual(opened, [path])
            self.assertEqual(path.read_text(encoding="utf-8"), "O mar canta baixo\nnas noites de estrela.\n")
            self.assertEqual(path.name, "poema-mar_2026-10-03_144210.txt")
            self.assertIn("um poema sobre o mar", prompts[0])

    def test_dictated_text_is_literal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            writer, _ = self.writer(Path(tmp), lambda _p: "NÃO DEVIA SER USADO")
            result = writer.notepad_write("comprar pão, leite e café")
            self.assertFalse(result["composed"])
            self.assertEqual(Path(result["path"]).read_text(encoding="utf-8").strip(), "comprar pão, leite e café")

    def test_without_model_writes_the_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            writer, _ = self.writer(Path(tmp))
            result = writer.notepad_write("um poema sobre o mar")
            self.assertFalse(result["composed"])

    def test_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            writer, _ = self.writer(Path(tmp), lambda _p: "   ")
            self.assertFalse(writer.notepad_write("").get("success", True))
            self.assertFalse(writer.notepad_write("um poema").get("success", True))

    def test_helpers(self) -> None:
        self.assertTrue(needs_composing("um poema sobre o mar"))
        self.assertTrue(needs_composing("lista de compras para churrasco"))
        self.assertFalse(needs_composing("oi, tudo bem"))
        self.assertFalse(needs_composing('"um poema"'))
        self.assertEqual(slug("Uma carta para a Ana!"), "carta-ana")


class AgentSequenceTests(TempDirTestCase):
    def make_agent(self) -> Any:
        import os
        from unittest import mock

        from brain.agent_loop import AgentLoop
        from brain.model import NullModel
        from computer.workspace import Workspace
        from memory.memory import Memory

        with mock.patch.dict(os.environ, {"DUQUE_FORGE": "0"}):
            agent = AgentLoop(tasks=self.tasks, workspace=Workspace(self.tmp / "ws"), model=NullModel(), memory=Memory(self.database))
        self.addCleanup(agent.scheduled_runner.stop)
        return agent

    def test_runs_each_step_in_order(self) -> None:
        agent = self.make_agent()
        calls: list[str] = []
        agent.executor.register("volume", lambda direction, steps=2: calls.append(f"volume {direction}") or {"message": "Volume ajustado."})
        result = agent.handle("aumente o volume e anote que o teste passou")
        self.assertIn("Volume ajustado.", result.text)
        self.assertIn("volume up", calls)
        notes = agent.assistant_tools.notes_list().get("notes", [])
        self.assertIn("o teste passou", [note["text"] for note in notes])

    def test_merged_youtube_request_plays(self) -> None:
        agent = self.make_agent()
        played: list[str] = []
        agent.executor.register("youtube_play", lambda query: played.append(query) or {"message": f"Tocando '{query}' no YouTube."})
        result = agent.handle("abra o youtube e reproduza Numb do Linkin Park")
        self.assertEqual(played, ["Numb do Linkin Park"])
        self.assertIn("Tocando", result.text)


class VoiceStyleTests(unittest.TestCase):
    def test_natural_style(self) -> None:
        from brain import voice_style

        self.assertEqual(voice_style.DEFAULT_VOICE, "cedar")
        self.assertNotIn("mordomo britânico sofisticado", voice_style.TTS_INSTRUCTIONS)
        self.assertIn("conversa", voice_style.VOICE_DELIVERY)
        self.assertGreater(voice_style.TTS_SPEED, 1.05)


@unittest.skipUnless(importlib.util.find_spec("openai") is not None, "servidor exige o pacote openai")
class StreamingSpeechTests(unittest.TestCase):
    def test_streaming_endpoint(self) -> None:
        from unittest import mock

        from tests.test_conversation import ServerConversationTests

        ServerConversationTests.setUpClass()
        try:
            servidor = ServerConversationTests.servidor
            client = servidor.app.test_client()
            self.assertEqual(client.get("/api/fala").status_code, 400)

            class Streamed:
                def __enter__(self) -> "Streamed":
                    return self

                def __exit__(self, *_: Any) -> None:
                    return None

                def iter_bytes(self, _size: int) -> Any:
                    yield b"ID3"
                    yield b"audio"

            fake = mock.MagicMock()
            fake.audio.speech.with_streaming_response.create.return_value = Streamed()
            with mock.patch.object(servidor, "openai_client", fake):
                response = client.get("/api/fala?text=ol%C3%A1")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data, b"ID3audio")
                kwargs = fake.audio.speech.with_streaming_response.create.call_args.kwargs
                self.assertEqual(kwargs["input"], "olá")
        finally:
            ServerConversationTests.tearDownClass()


class HudLayoutTests(unittest.TestCase):
    def test_right_column_is_one_stack(self) -> None:
        html = (Path(__file__).resolve().parent.parent / "interface" / "index.html").read_text(encoding="utf-8")
        rail = html.index('<div id="rail">')
        for element in ('id="telemetry"', 'id="chat"', 'id="forge"'):
            self.assertGreater(html.index(element), rail, element)
        self.assertNotIn("#chat{position:absolute", html)
        self.assertIn("new Audio('/api/fala?'", html)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(
    all(importlib.util.find_spec(name) is not None for name in ("numpy", "sounddevice", "agents", "openwakeword")),
    "runtime de voz exige os pacotes de áudio",
)
class PlaybackBufferTests(unittest.TestCase):
    """A fala só começa com um colchão de áudio guardado (voz sem picotes)."""

    def test_waits_for_buffer_then_plays(self) -> None:
        import duque_wake_v2 as runtime

        runtime.clear_audio()
        runtime.FENCE.new_session()
        frames = 480
        out = bytearray(frames * 2)
        small = b"\x01\x00" * 480  # 20 ms
        runtime.enqueue_audio(small, "item", 0)
        runtime.output_callback(out, frames, None, None)
        self.assertEqual(bytes(out), b"\x00" * len(out))  # ainda esperando o colchão
        runtime.enqueue_audio(b"\x01\x00" * runtime.PREBUFFER_BYTES, "item", 0)
        runtime.output_callback(out, frames, None, None)
        self.assertEqual(bytes(out), small)  # agora toca, na ordem
        runtime.clear_audio()
        self.assertFalse(runtime.PLAYING)
