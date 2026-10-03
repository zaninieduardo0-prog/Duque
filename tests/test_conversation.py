from __future__ import annotations

import importlib.util
import os
import unittest
from typing import Any
from unittest import mock

from brain.agent_loop import AgentLoop
from brain.model import NullModel
from brain.persona import text_system_prompt, voice_instructions
from computer.workspace import Workspace
from core.voice_bridge import VoiceBridge
from memory.conversation import ConversationStore
from memory.memory import Memory
from tests.helpers import ScriptedModel, TempDirTestCase
from voice.transcripts import speech_from_event


class ConversationStoreTests(TempDirTestCase):
    def test_turns_are_ordered_and_filtered(self) -> None:
        store = ConversationStore()
        store.add("user", "oi", "texto")
        store.add("assistant", "Olá, Du.", "texto")
        store.add("user", "abre o spotify", "voz")
        self.assertIsNone(store.add("system", "x"))
        self.assertIsNone(store.add("user", "   "))
        self.assertEqual([turn.text for turn in store.since(1)], ["Olá, Du.", "abre o spotify"])
        self.assertEqual(store.as_messages(2), [{"role": "assistant", "content": "Olá, Du."}, {"role": "user", "content": "abre o spotify"}])
        self.assertIn("Du (voz): abre o spotify", store.transcript())

    def test_duplicate_events_are_ignored(self) -> None:
        store = ConversationStore()
        first = store.add("user", "que horas são", "voz")
        second = store.add("user", "que horas são", "voz")
        self.assertEqual(first, second)
        self.assertEqual(store.last_id(), 1)

    def test_survives_restart(self) -> None:
        memory = Memory(self.database)
        ConversationStore(memory).add("user", "lembra disso", "texto")
        restored = ConversationStore(memory)
        self.assertEqual(restored.recent()[0].text, "lembra disso")
        self.assertEqual(restored.add("assistant", "lembro", "voz").id, 2)  # type: ignore[union-attr]


class Obj:
    def __init__(self, **values: Any) -> None:
        self.__dict__.update(values)


class TranscriptTests(unittest.TestCase):
    def test_typed_sdk_event(self) -> None:
        event = Obj(type="raw_model_event", data=Obj(type="input_audio_transcription_completed", transcript=" abre o chrome "))
        self.assertEqual(speech_from_event(event), ("user", "abre o chrome"))

    def test_raw_server_events(self) -> None:
        user = Obj(type="raw_model_event", data=Obj(type="raw_server_event", data={"type": "conversation.item.input_audio_transcription.completed", "transcript": "oi"}))
        duque = Obj(type="raw_model_event", data=Obj(type="raw_server_event", data={"type": "response.output_audio_transcript.done", "transcript": "Olá, Du."}))
        self.assertEqual(speech_from_event(user), ("user", "oi"))
        self.assertEqual(speech_from_event(duque), ("assistant", "Olá, Du."))

    def test_ignores_other_events(self) -> None:
        self.assertIsNone(speech_from_event(Obj(type="audio")))
        self.assertIsNone(speech_from_event(Obj(type="raw_model_event", data=Obj(type="transcript_delta", delta="o"))))


class PersonaAndBridgeTests(unittest.TestCase):
    def test_persona(self) -> None:
        self.assertIn("TELEX", text_system_prompt())
        self.assertIn("senhor", text_system_prompt())  # regra de nunca usar "senhor"
        instructions = voice_instructions("Du (texto): abre o spotify")
        self.assertIn("CONVERSA ATÉ AGORA", instructions)
        self.assertIn("abre o spotify", instructions)
        self.assertNotIn("CONVERSA ATÉ AGORA", voice_instructions(""))

    def test_bridge_routes_in_process(self) -> None:
        bridge = VoiceBridge()
        recorded: list[tuple[str, str, str]] = []
        bridge.attach_core(executor=lambda text: f"feito: {text}", recorder=lambda *args: recorded.append(args), context=lambda: "ctx")
        self.assertEqual(bridge.execute("abre o chrome"), "feito: abre o chrome")
        bridge.record("user", "oi", "voz")
        self.assertEqual(recorded, [("user", "oi", "voz")])
        self.assertEqual(bridge.context(), "ctx")

        self.assertFalse(bridge.voice_active)
        self.assertFalse(bridge.send_to_voice("x"))
        sent: list[str] = []
        bridge.attach_session(lambda text: sent.append(text) or True)
        self.assertTrue(bridge.voice_active)
        self.assertTrue(bridge.send_to_voice("continua"))
        bridge.detach_session()
        self.assertFalse(bridge.voice_active)
        self.assertEqual(sent, ["continua"])


class AgentConversationTests(TempDirTestCase):
    def make_agent(self, model: Any) -> AgentLoop:
        with mock.patch.dict(os.environ, {"DUQUE_FORGE": "0"}):
            agent = AgentLoop(tasks=self.tasks, workspace=Workspace(self.tmp / "ws"), model=model, memory=Memory(self.database))
        self.addCleanup(agent.scheduled_runner.stop)
        return agent

    def test_chat_uses_shared_history_and_persona(self) -> None:
        model = ScriptedModel(["Spotify aberto há pouco, Du.", "Foi o Spotify."])
        agent = self.make_agent(model)
        agent.conversation.add("user", "abre o spotify", "voz")
        agent.conversation.add("assistant", "Abri o Spotify.", "voz")
        # Chat puro: o planner do modelo devolve texto não-JSON e cai na resposta conversacional.
        model.replies.insert(0, "sem plano")
        result = agent.handle("o que você abriu por último?")

        messages = model.calls[-1]
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("TELEX", messages[0]["content"])
        self.assertIn({"role": "user", "content": "abre o spotify"}, messages)
        self.assertEqual(messages[-1], {"role": "user", "content": "o que você abriu por último?"})
        self.assertEqual(result.text, "Spotify aberto há pouco, Du.")
        texts = [(turn.role, turn.channel, turn.text) for turn in agent.conversation.recent(2)]
        self.assertEqual(texts, [("user", "texto", "o que você abriu por último?"), ("assistant", "texto", "Spotify aberto há pouco, Du.")])

    def test_tool_result_message_is_used(self) -> None:
        agent = self.make_agent(NullModel())
        result = agent.handle("quanto é 6*7?")
        self.assertEqual(result.text, "6*7 = 42")

    def test_voice_tool_calls_do_not_duplicate_turns(self) -> None:
        agent = self.make_agent(NullModel())
        agent.handle("que horas são?", channel="voz", record=False)
        self.assertEqual(agent.conversation.recent(), [])

    def test_announcements_enter_conversation(self) -> None:
        agent = self.make_agent(NullModel())
        agent.announce("Du, o timer terminou.")
        turn = agent.conversation.recent(1)[0]
        self.assertEqual((turn.role, turn.channel), ("assistant", "aviso"))


@unittest.skipUnless(importlib.util.find_spec("openai") is not None, "servidor exige o pacote openai")
class ServerConversationTests(unittest.TestCase):
    """Importa o servidor dentro de uma pasta temporária.

    O servidor cria o AgentLoop com o banco em "duque_data/" relativo à pasta
    atual. Sem isolamento, rodar os testes na instalação real (Forja,
    diagnóstico, preparar_duque.bat) usaria o banco do Du: dispararia lembretes
    de verdade e escreveria na conversa real.
    """

    @classmethod
    def setUpClass(cls) -> None:
        import importlib
        import sys
        import tempfile

        cls._tmp = tempfile.TemporaryDirectory()
        cls._cwd = os.getcwd()
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        os.makedirs(os.path.join(cls._tmp.name, "interface"), exist_ok=True)
        cls._env = mock.patch.dict(os.environ, {
            "DUQUE_WORKSPACE_ROOT": cls._tmp.name,
            "DUQUE_FORGE": "0",
            "DUQUE_DAILY_SUMMARY": "0",
            "OPENAI_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
        })
        cls._env.start()
        os.chdir(cls._tmp.name)
        if root not in sys.path:
            sys.path.insert(0, root)
        sys.modules.pop("servidor", None)
        cls.servidor = importlib.import_module("servidor")
        if os.path.abspath(cls.servidor.agent.tasks.database.path).startswith(os.path.abspath(root)):
            raise AssertionError("o teste do servidor não pode usar o banco da instalação")

    @classmethod
    def tearDownClass(cls) -> None:
        import sys

        cls.servidor.agent.scheduled_runner.stop()
        cls.servidor.bridge.detach_session()
        sys.modules.pop("servidor", None)
        os.chdir(cls._cwd)
        cls._env.stop()
        cls._tmp.cleanup()

    def setUp(self) -> None:
        self.client = self.servidor.app.test_client()
        self.addCleanup(self.servidor.bridge.detach_session)

    def test_conversation_endpoints(self) -> None:
        response = self.client.post("/api/conversa", json={"role": "user", "text": "teste de voz", "canal": "voz"})
        self.assertEqual(response.status_code, 200)
        data = self.client.get("/api/conversa").get_json()
        self.assertIn("teste de voz", [turn["text"] for turn in data["turnos"]])
        self.assertIn("texto", self.client.get("/api/conversa?formato=texto").get_json())

    def test_typed_text_goes_to_active_voice_session(self) -> None:
        sent: list[str] = []
        self.servidor.bridge.attach_session(lambda text: sent.append(text) or True)
        data = self.client.post("/api/comando", json={"text": "e amanhã?"}).get_json()
        self.assertEqual(data["via"], "voz")
        self.assertEqual(sent, ["e amanhã?"])

    def test_memory_and_greeting_endpoints(self) -> None:
        from tests.test_memory_features import fake_weather

        self.servidor.agent.assistant_tools.fetch_json = fake_weather
        self.assertEqual(self.client.post("/api/memoria/notas", json={"texto": "gosta de jazz"}).status_code, 200)
        notes = self.client.get("/api/memoria").get_json()["notas"]
        self.assertIn("gosta de jazz", [note["text"] for note in notes])
        self.assertIn("gosta de jazz", self.client.get("/api/memoria?formato=texto").get_json()["texto"])
        self.assertEqual(self.client.delete(f"/api/memoria/notas/{len(notes)}").status_code, 200)
        self.assertEqual(self.client.delete("/api/memoria/notas/999").status_code, 404)

        self.servidor._ultima_saudacao["em"] = 0.0
        first = self.client.post("/api/saudacao").get_json()
        self.assertTrue(first["ok"])
        self.assertIn("Sistemas online", first["text"])
        self.assertFalse(self.client.post("/api/saudacao").get_json()["ok"])

    def test_media_endpoints(self) -> None:
        status = self.client.get("/api/midia").get_json()
        self.assertIn("playing", status)
        self.assertEqual(self.client.post("/api/midia", json={"acao": "dançar"}).status_code, 400)

    def test_voice_tool_runs_while_listening(self) -> None:
        """Regressão: ouvindo -> executando não existe e derrubava a ferramenta da voz."""
        from core.state import DuqueState

        self.servidor.agent.engine.transition(DuqueState.LISTENING, force=True)
        self.assertEqual(self.servidor._execute_for_voice("quanto é 2+3?"), "2+3 = 5")

    def test_command_from_sleeping_state(self) -> None:
        from core.state import DuqueState

        self.servidor.agent.engine.transition(DuqueState.SLEEPING, force=True)
        response = self.client.post("/api/comando", json={"text": "quanto é 1+1?"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["text"], "1+1 = 2")

    def test_typed_text_without_voice_is_answered(self) -> None:
        data = self.client.post("/api/comando", json={"text": "quanto é 2+3?"}).get_json()
        self.assertEqual(data["text"], "2+3 = 5")


if __name__ == "__main__":
    unittest.main()
