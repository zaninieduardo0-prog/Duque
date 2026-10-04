"""Ajustes 14: ativação mais sensível ("oi, TELEX", ganho do microfone) e pedidos com várias tarefas."""

from __future__ import annotations

import array
import os
import unittest
from typing import Any
from unittest import mock

from brain.compound import plan_steps
from tests.helpers import TempDirTestCase
from voice.local_wake import boost, classify, decide, grammar


class WakeTests(unittest.TestCase):
    def test_greeting_wake_is_unchanged(self) -> None:
        self.assertEqual(decide(classify("bom dia telex"), False, False), ("wake", "Bom dia, TELEX."))
        self.assertIsNone(classify("bom dia"))
        self.assertIsNone(classify("oi telex"))
        self.assertNotIn("oi telex", grammar())

    def test_quiet_microphone_is_boosted(self) -> None:
        quiet = array.array("h", [3600, -3600] * 800).tobytes()  # pico ~0.11, como no teste do Du
        out, peak = boost(quiet, 0.0)
        samples = array.array("h")
        samples.frombytes(out)
        self.assertGreater(max(samples) / 32768.0, 0.25)
        self.assertAlmostEqual(peak, 3600 / 32768.0, places=3)

    def test_silence_and_loud_audio_are_untouched(self) -> None:
        silence = b"\0" * 1600
        self.assertEqual(boost(silence, 0.0)[0], silence)
        loud = array.array("h", [20000, -20000] * 800).tobytes()
        self.assertEqual(boost(loud, 0.0)[0], loud)

    def test_gain_is_capped(self) -> None:
        faint = array.array("h", [400, -400] * 800).tobytes()  # pico ~0.012
        out, _ = boost(faint, 0.0)
        samples = array.array("h")
        samples.frombytes(out)
        self.assertLessEqual(max(samples), 400 * 6 + 1)


class MultiTaskSplitTests(unittest.TestCase):
    def test_sentences_and_links_split(self) -> None:
        self.assertEqual(
            plan_steps("abra o chrome. Pesquise o dólar. Depois feche o chrome"),
            ["abra o chrome", "Pesquise o dólar", "feche o chrome"],
        )
        self.assertEqual(
            plan_steps("abra o spotify, além disso aumente o volume e por fim anote que terminei"),
            ["abra o spotify", "aumente o volume", "anote que terminei"],
        )

    def test_ordinals_are_dropped(self) -> None:
        self.assertEqual(
            plan_steps("primeiro abra o chrome, depois pesquise o dólar"),
            ["abra o chrome", "pesquise o dólar"],
        )

    def test_new_verbs_split(self) -> None:
        self.assertEqual(
            plan_steps("ligue o bluetooth e abaixe o volume"),
            ["ligue o bluetooth", "abaixe o volume"],
        )

    def test_content_is_still_one_step(self) -> None:
        for text in (
            "escreva um poema sobre amor e paixão",
            "anote que preciso ligar e desligar o gás",
            "que horas são. Obrigado",
        ):
            with self.subTest(text=text):
                self.assertEqual(len(plan_steps(text)), 1)


class SequenceResilienceTests(TempDirTestCase):
    def make_agent(self) -> Any:
        from brain.agent_loop import AgentLoop
        from brain.model import NullModel
        from computer.workspace import Workspace
        from memory.memory import Memory

        with mock.patch.dict(os.environ, {"DUQUE_FORGE": "0"}):
            agent = AgentLoop(tasks=self.tasks, workspace=Workspace(self.tmp / "ws"), model=NullModel(), memory=Memory(self.database))
        self.addCleanup(agent.scheduled_runner.stop)
        return agent

    def test_independent_step_runs_after_a_failure(self) -> None:
        agent = self.make_agent()
        calls: list[str] = []

        def volume(direction: str, steps: int = 2) -> dict[str, str]:
            calls.append(direction)
            return {"message": "Volume ajustado."}

        agent.executor.register("volume", volume)
        original = agent._handle

        def flaky(step: str, **kwargs: Any) -> Any:
            if "volume" not in step:
                from brain.agent_loop import AgentResult

                return AgentResult("Não consegui abrir isso.")
            return original(step, **kwargs)

        with mock.patch.object(agent, "_handle", side_effect=flaky):
            result = agent._handle_sequence(["abra o app inexistente", "aumente o volume"], confirmed=False, max_attempts=1)
        self.assertEqual(calls, ["up"])
        self.assertIn("Volume ajustado.", result.text)
        self.assertIn("Na etapa 1", result.text)

    def test_dependent_step_is_skipped_after_a_failure(self) -> None:
        agent = self.make_agent()
        seen: list[str] = []

        def fake(step: str, **_kwargs: Any) -> Any:
            from brain.agent_loop import AgentResult

            seen.append(step)
            return AgentResult("Não consegui abrir.")

        with mock.patch.object(agent, "_handle", side_effect=fake):
            result = agent._handle_sequence(["abra o app", "toque música lá"], confirmed=False, max_attempts=1)
        self.assertEqual(seen, ["abra o app"])
        self.assertIn("Pulei a etapa 2", result.text)


if __name__ == "__main__":
    unittest.main()
