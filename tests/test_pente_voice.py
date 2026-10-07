"""Pente fino da voz: um runtime só, sem travas, sem ações duplicadas."""

from __future__ import annotations

import asyncio
import importlib.util
import time
import unittest
from pathlib import Path
from unittest import mock

from voice.devices import pick_wake_device
from voice.local_session import Deps, LocalSession
from voice.local_tts import Audio
from voice.local_wake import classify

ROOT = Path(__file__).resolve().parent.parent
AUDIO_STACK = all(importlib.util.find_spec(n) for n in ("numpy", "sounddevice", "agents", "openwakeword", "pvrecorder", "pedalboard"))


class SingleVoicePathTests(unittest.TestCase):
    def test_superseded_entry_points_are_gone(self) -> None:
        self.assertFalse((ROOT / "duque_voz.py").exists())  # caminho antigo com outro AgentLoop
        self.assertFalse((ROOT / "voice" / "session_lifecycle.py").exists())  # nunca usado
        # O v3 trocava funções do v2 em tempo de execução; agora há um runtime só.
        self.assertFalse((ROOT / "duque_wake_v3.py").exists())
        self.assertIn("import duque_wake_v2", (ROOT / "duque.py").read_text(encoding="utf-8"))


class DeviceTests(unittest.TestCase):
    def test_non_numeric_mic_setting_does_not_kill_voice(self) -> None:
        index, reason = pick_wake_device(["Mic A", "Mic B"], env={"DUQUE_WAKE_MIC": "Mic B"})
        self.assertEqual(index, 0)
        self.assertIn("ignorado", reason)


class LooseWakeTests(unittest.TestCase):
    def test_common_words_do_not_wake(self) -> None:
        for text in ("telefone tocou", "telefona pra ela", "telhado"):
            with self.subTest(text=text):
                self.assertIsNone(classify(text, loose=True))
        self.assertEqual(classify("tele", loose=True).kind, "call")  # type: ignore[union-attr]


class LocalPauseTests(unittest.TestCase):
    def test_pause_command_reaches_control_instead_of_just_stopping(self) -> None:
        frames = [b"\x00\x40" * 1280] * 5 + [b"\x00\x00" * 1280] * 40
        handled: list[str] = []
        thought: list[str] = []
        deps = Deps(
            read_frame=lambda: frames.pop(0) if frames else b"",
            transcribe=lambda _pcm: "Telex, pausa tudo",
            synthesize=lambda _t: Audio(b"", 16000),
            play=lambda _a: None,
            think=lambda text: thought.append(text) or "ok",
            control=lambda text: handled.append(text) or True,
        )
        reason = LocalSession(deps).converse(None, call=True)
        self.assertEqual(reason, "controle")
        self.assertEqual(handled, ["Telex, pausa tudo"])
        self.assertEqual(thought, [])


@unittest.skipUnless(AUDIO_STACK, "runtime de voz exige os pacotes de áudio")
class RuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        import duque_wake_v2 as runtime

        self.rt = runtime
        runtime.clear_audio()
        runtime.FENCE.new_session()
        with runtime.CANCELLED_LOCK:
            runtime.CANCELLED.clear()
        runtime.CURRENT_ITEM = None

    def tearDown(self) -> None:
        self.rt.clear_audio()
        self.rt.FENCE.close()
        self.rt.CURRENT_ITEM = None

    def test_chime_never_becomes_current_item(self) -> None:
        rt = self.rt
        rt.enqueue_audio(b"\x01\x00" * 100, "resp_1", 0)
        rt.play_chime()
        self.assertEqual(rt.CURRENT_ITEM, "resp_1")

    def test_interrupt_cancels_the_response_and_keeps_chimes(self) -> None:
        rt = self.rt
        rt.enqueue_audio(b"\x01\x00" * 100, "resp_1", 0)

        class Session:
            async def interrupt(self) -> None:
                pass

        with mock.patch.object(rt, "SESSION", Session()):
            asyncio.run(rt.interrupt_session())
        self.assertTrue(rt.cancelled("resp_1"))
        rt.enqueue_audio(b"\x01\x00" * 100, "resp_1", 0)  # trecho atrasado da resposta cortada
        rt.play_chime()
        self.assertEqual({item for item, _i, _d in rt.AUDIO}, {"telex-chime"})

    def test_wait_playback_gives_up_when_speaker_stalls(self) -> None:
        rt = self.rt
        rt.enqueue_audio(b"\x01\x00" * 24000, "resp_1", 0)  # ninguém consome (sem alto-falante)
        started = time.monotonic()
        asyncio.run(rt.wait_playback(stall_seconds=0.3))
        self.assertLess(time.monotonic() - started, 3.0)
        self.assertEqual(rt.queued_bytes(), 0)

    def test_stuck_conversation_expires(self) -> None:
        rt = self.rt
        with mock.patch.object(rt.FLOW, "state", "speaking"):
            self.assertFalse(rt.idle_expired(rt.LAST_ACTIVITY + rt.IDLE_SECONDS + 1))
            self.assertTrue(rt.idle_expired(rt.LAST_ACTIVITY + rt.STUCK_SECONDS + 1))

    def test_hud_does_not_block(self) -> None:
        rt = self.rt
        with mock.patch.object(rt, "_post_hud", side_effect=lambda *_a: time.sleep(1.0)):
            started = time.monotonic()
            for _ in range(5):
                rt.hud("ouvindo", "x")
            self.assertLess(time.monotonic() - started, 0.3)

    def test_farewell_waits_for_reply_before_closing(self) -> None:
        rt = self.rt

        async def scenario() -> list[str]:
            order: list[str] = []
            rt.SHUTDOWN_EVENT = asyncio.Event()
            task = asyncio.create_task(rt.finish_shutdown(reply_wait=2.0, reply_limit=5.0))
            await asyncio.sleep(0.3)
            self.assertFalse(rt.SHUTDOWN_EVENT.is_set())  # a despedida ainda nem começou
            rt.RESPONDING = True
            order.append("resposta começou")
            await asyncio.sleep(0.3)
            rt.RESPONDING = False
            order.append("resposta terminou")
            await asyncio.wait_for(task, 3.0)
            order.append("fechou")
            return order

        try:
            self.assertEqual(asyncio.run(scenario()), ["resposta começou", "resposta terminou", "fechou"])
        finally:
            rt.RESPONDING = False
            rt.SHUTDOWN_EVENT = None

    def test_watched_tasks_survive_shutdown_so_farewell_is_not_cut(self) -> None:
        rt = self.rt

        async def scenario() -> tuple[bool, bool]:
            tasks = [asyncio.create_task(rt.idle_watch()), asyncio.create_task(rt.flow_ticker(object()))]
            await asyncio.sleep(1.3)
            alive = tuple(not task.done() for task in tasks)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            return alive  # type: ignore[return-value]

        with mock.patch.object(rt, "REALTIME", True), mock.patch.object(rt, "SHUTTING_DOWN", True):
            self.assertEqual(asyncio.run(scenario()), (True, True))

    def test_announcement_is_spoken_once_and_not_recorded_twice(self) -> None:
        rt = self.rt
        self.assertFalse(rt.announce("Lembrete: reunião às 15h."))  # sem conversa ativa

        sent: list[str] = []

        class Session:
            async def send_message(self, text: str) -> None:
                sent.append(text)

        async def scenario() -> None:
            rt.LOOP = asyncio.get_running_loop()
            rt.SESSION = Session()
            self.assertTrue(rt.announce("Lembrete: reunião às 15h."))
            await asyncio.sleep(0.1)

        try:
            asyncio.run(scenario())
        finally:
            rt.LOOP = None
            rt.SESSION = None
        self.assertEqual(len(sent), 1)
        self.assertIn("reunião às 15h", sent[0])
        self.assertTrue(rt.is_announcement("Lembrete: reunião às 15h."))
        self.assertFalse(rt.is_announcement("Lembrete: reunião às 15h."))  # só uma vez

    def test_spawn_logs_failures(self) -> None:
        rt = self.rt
        logged: list[str] = []

        async def boom() -> None:
            raise RuntimeError("falhou")

        async def scenario() -> None:
            rt.spawn(boom(), "teste")
            await asyncio.sleep(0.05)

        with mock.patch.object(rt, "log", side_effect=logged.append):
            asyncio.run(scenario())
        self.assertTrue(any("falhou" in line for line in logged))
        self.assertEqual(rt.TASKS, set())

    def test_offline_openai_falls_back_to_local_conversation(self) -> None:
        rt = self.rt
        local = mock.Mock()

        async def not_connected(*_a, **_k) -> bool:
            return False

        with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "k", "DUQUE_VOICE": "auto"}), \
                mock.patch.object(rt, "realtime_session", side_effect=not_connected), \
                mock.patch.object(rt, "OPENAI_BLOCKED", False):
            rt.converse(local, None, "call", b"")
        local.run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
