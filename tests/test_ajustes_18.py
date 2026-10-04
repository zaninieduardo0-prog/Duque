"""Ajustes 18: revisão final — autonomia com modelo pequeno, bipe sem eco e fala longa."""

from __future__ import annotations

import os
import unittest
from typing import Any
from unittest import mock

from brain.autonomous_loop import AutonomousLoop
from voice import local_session
from voice.local_session import Deps, LocalSession
from voice.local_tts import Audio


class ParseTests(unittest.TestCase):
    def loop(self) -> AutonomousLoop:
        return AutonomousLoop(model=mock.Mock(), executor=mock.Mock(), schemas=mock.Mock())

    def test_json_inside_chatty_text_is_accepted(self) -> None:
        action = self.loop()._parse_action('Claro! Aqui vai: {"action":"finish","message":"pronto"} Espero ter ajudado.')
        self.assertEqual(action["action"], "finish")

    def test_garbage_is_still_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.loop()._parse_action("não sei fazer isso")

    def test_unknown_action_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.loop()._parse_action('{"action":"dancar"}')


class GiveUpTests(unittest.TestCase):
    def test_stops_after_repeated_unusable_answers(self) -> None:
        from brain.agent_state import AgentContext

        model = mock.Mock()
        model.respond.return_value = mock.Mock(text="blablabla sem json")
        executor = mock.Mock()
        executor.tasks.get.return_value = mock.Mock(id="t1")
        schemas = mock.Mock()
        schemas.describe.return_value = []
        loop = AutonomousLoop(model=model, executor=executor, schemas=schemas, max_steps=160)
        result = loop.run(AgentContext(goal="faça algo", task_id="t1"))
        self.assertFalse(result.success)
        self.assertEqual(model.respond.call_count, loop.invalid_limit)  # não gasta os 160 passos
        self.assertIn("formato", result.message)


class OperatorTests(unittest.TestCase):
    def agent(self, model: Any) -> Any:
        from brain.agent_loop import AgentLoop

        agent = object.__new__(AgentLoop)
        agent.model = model
        return agent

    def test_operator_off_for_pure_local_model_unless_enabled(self) -> None:
        from brain.model import OllamaModel

        env = {k: v for k, v in os.environ.items() if k != "DUQUE_OPERATOR"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertFalse(self.agent(OllamaModel())._operator_available())
        with mock.patch.dict(os.environ, {"DUQUE_OPERATOR": "1"}):
            self.assertTrue(self.agent(OllamaModel())._operator_available())

    def test_operator_on_with_api_model_by_default(self) -> None:
        from brain.model import ChainModel, NullModel

        env = {k: v for k, v in os.environ.items() if k != "DUQUE_OPERATOR"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertTrue(self.agent(ChainModel([mock.Mock()]))._operator_available())
            self.assertFalse(self.agent(NullModel())._operator_available())


class SpeechTests(unittest.TestCase):
    def test_long_reply_is_cut_at_a_sentence(self) -> None:
        text = "Primeira frase. " * 60
        short = LocalSession.shorten(text)
        self.assertLessEqual(len(short), local_session.MAX_SPOKEN_CHARS + 40)
        self.assertTrue(short.endswith("O resto está na tela."))
        self.assertEqual(LocalSession.shorten("Curta."), "Curta.")

    def test_chime_plays_with_microphone_closed(self) -> None:
        events: list[str] = []
        deps = Deps(
            read_frame=lambda: b"",
            transcribe=lambda _p: "",
            synthesize=lambda _t: Audio(b"", 16000),
            play=lambda _a: None,
            think=lambda _r: "",
            chime=lambda: events.append("bipe"),
            mute_mic=lambda: events.append("fecha"),
            unmute_mic=lambda: events.append("abre"),
        )
        LocalSession(deps).chime()
        self.assertEqual(events, ["fecha", "bipe", "abre"])


if __name__ == "__main__":
    unittest.main()
