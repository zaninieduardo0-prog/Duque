"""Ajustes 12: conversa por voz do jeito do Du, desligar, fechar só a aba e prestatividade."""

from __future__ import annotations

import asyncio
import importlib.util
import unittest
from typing import Any
from unittest import mock

from computer.assistant_tools import AssistantTools
from computer.whatsapp_flow import CURRENT_PROFILE, WhatsAppDesktop, parse_request, split_profile
from core.emergency import is_shutdown_command
from voice.conversation_flow import VoiceFlow, greeting_reply
from voice.local_wake import classify, decide


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class VoiceFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = Clock()
        self.flow = VoiceFlow(clock=self.clock)

    def wait(self, seconds: float) -> str:
        self.clock.now += seconds
        return self.flow.tick()

    def test_greeting_reply(self) -> None:
        self.assertEqual(greeting_reply("Boa tarde, TELEX."), "Boa tarde, Du. À sua disposição.")
        self.assertEqual(greeting_reply("bom dia telex"), "Bom dia, Du. À sua disposição.")

    def test_after_greeting_waits_5s_then_asks_to_continue(self) -> None:
        self.flow.on_speaking()
        self.flow.on_greeting_done(has_previous=True)
        self.assertEqual(self.wait(4.9), "none")
        self.assertEqual(self.wait(0.2), "ask_resume")
        self.flow.on_reply_done("Quer que eu continue de onde parei?")
        self.assertEqual(self.flow.on_transcript("sim"), "resume")

    def test_resume_no_or_silence_goes_to_standby(self) -> None:
        for answer in ("não", None):
            with self.subTest(answer=answer):
                flow = VoiceFlow(clock=self.clock)
                flow.on_greeting_done(has_previous=True)
                self.clock.now += 6
                flow.tick()
                flow.on_reply_done("Quer que eu continue de onde parei?")
                if answer:
                    self.assertEqual(flow.on_transcript(answer), "standby")
                else:
                    self.clock.now += 6
                    self.assertEqual(flow.tick(), "standby")
                self.assertEqual(flow.state, "standby")

    def test_without_previous_conversation_just_standby(self) -> None:
        self.flow.on_greeting_done(has_previous=False)
        self.assertEqual(self.wait(6), "standby")

    def test_long_question_is_waited_for(self) -> None:
        """Enquanto ele fala, o prazo não corre — nem que demore minutos."""
        self.flow.on_greeting_done(has_previous=True)
        self.flow.on_speech_started()
        self.assertEqual(self.wait(180), "none")
        self.assertEqual(self.flow.on_transcript("primeiro pedaço da pergunta"), "collect")
        self.flow.on_speech_started()  # pausa curta e continuou falando
        self.assertEqual(self.wait(5), "none")
        self.assertEqual(self.flow.on_transcript("e o resto dela"), "collect")
        self.flow.on_speech_stopped()
        self.assertEqual(self.wait(1.5), "respond")
        self.assertEqual(self.flow.take_collected(), "primeiro pedaço da pergunta e o resto dela")

    def test_name_alone_chimes_and_listens(self) -> None:
        self.assertEqual(self.flow.on_transcript("Telex."), "chime")
        self.assertEqual(self.flow.on_transcript("abre o youtube"), "collect")
        self.assertEqual(self.wait(1.5), "respond")

    def test_name_and_request_together(self) -> None:
        self.assertEqual(self.flow.on_transcript("Telex, abra meu WhatsApp Web no perfil em que estou"), "collect")
        self.assertEqual(self.wait(1.5), "respond")

    def test_standby_ignores_everything_without_name(self) -> None:
        self.assertEqual(self.flow.on_transcript("abre o youtube"), "ignore")

    def test_only_telex_interrupts(self) -> None:
        self.flow.on_speaking()
        for other in ("para", "chega", "nossa, que legal", "stop"):
            self.assertEqual(self.flow.on_transcript(other), "ignore", other)
        self.assertEqual(self.flow.on_transcript("Telex"), "interrupt_and_listen")
        self.assertEqual(self.wait(8.1), "standby")  # sem fala depois da interrupção

    def test_interrupt_with_new_request(self) -> None:
        self.flow.on_speaking()
        self.assertEqual(self.flow.on_transcript("Telex, abre o Spotify"), "interrupt_and_collect")

    def test_reply_ending_with_question_listens_5s(self) -> None:
        self.flow.on_speaking()
        self.flow.on_reply_done("Tocando. O volume está bom?")
        self.assertEqual(self.flow.on_transcript("aumenta um pouco"), "collect")
        flow = VoiceFlow(clock=self.clock)
        flow.on_speaking()
        self.assertEqual(flow.on_reply_done("Feito, senhor."), "standby")

    def test_listen_window_expires(self) -> None:
        self.flow.on_call()
        self.assertEqual(self.wait(8.1), "standby")


class WakeWordTests(unittest.TestCase):
    def test_name_first_greeting(self) -> None:
        self.assertEqual(decide(classify("telex boa tarde"), False, False), ("wake", "Boa tarde, TELEX."))
        self.assertEqual(decide(classify("boa noite telex"), False, False), ("wake", "Boa noite, TELEX."))
        self.assertEqual(decide(classify("telex"), False, False), ("call", None))


@unittest.skipUnless(all(importlib.util.find_spec(n) for n in ("numpy", "sounddevice", "agents", "openwakeword")), "runtime de voz")
class NoSelfInterruptTests(unittest.TestCase):
    def test_speech_started_does_not_cancel(self) -> None:
        import duque_wake_v2 as runtime
        from agents.realtime.openai_realtime import OpenAIRealtimeWebSocketModel

        model = runtime.new_model()
        self.assertIsInstance(model, runtime.TelexRealtimeModel)
        emitted: list[Any] = []

        async def emit(event: Any) -> None:
            emitted.append(event)

        with mock.patch.object(OpenAIRealtimeWebSocketModel, "_handle_ws_event") as parent, \
                mock.patch.object(model, "_emit_event", side_effect=emit):
            asyncio.run(model._handle_ws_event({"type": "input_audio_buffer.speech_started"}))
            parent.assert_not_called()
        self.assertEqual(len(emitted), 1)

    def test_chime(self) -> None:
        import duque_wake_v2 as runtime

        self.assertGreater(len(runtime.chime_audio()), 4000)


class ShutdownTests(unittest.TestCase):
    def test_phrases(self) -> None:
        for text in ("Telex, desligar", "desligue o TELEX", "pode se desligar", "feche o telex"):
            self.assertTrue(is_shutdown_command(text), text)
        for text in ("desligue o computador", "desliga a luz", "feche o youtube"):
            self.assertFalse(is_shutdown_command(text), text)


class CloseTabTests(unittest.TestCase):
    def test_closing_youtube_closes_only_its_tab(self) -> None:
        from computer.tools import ComputerTools

        with mock.patch("computer.windows_focus.close_tab", return_value=1) as close_tab, \
                mock.patch("subprocess.run") as run:
            result = ComputerTools().close_app("youtube")
        close_tab.assert_called_once_with("YouTube")
        run.assert_not_called()  # nada de taskkill no Chrome
        self.assertIn("aba do YouTube", result["message"])


class HelpfulYouTubeTests(unittest.TestCase):
    def test_sets_volume_and_asks(self) -> None:
        keys: list[tuple[int, int]] = []
        tools = AssistantTools(
            fetch_text=lambda _u: '"videoId":"abcdefghijk"', open_target=lambda _u: None,
            wait_window=lambda _f, _t: True, reuse_window=lambda _f, _u: False,
            press_key=lambda vk, times: keys.append((vk, times)),
        )
        result = tools.youtube_play("charlie brown jr")
        self.assertIn("O volume está bom?", result["message"])
        self.assertEqual(keys[-1][1], 15)  # 30% = 15 toques de 2%

    def test_volume_set(self) -> None:
        keys: list[tuple[int, int]] = []
        tools = AssistantTools(press_key=lambda vk, times: keys.append((vk, times)))
        self.assertEqual(tools.volume_set(50)["percent"], 50)
        self.assertEqual([times for _vk, times in keys], [50, 25])


class CurrentProfileTests(unittest.TestCase):
    def test_phrasing(self) -> None:
        self.assertEqual(split_profile("abra meu whatsapp web no perfil em que estou no momento")[0], CURRENT_PROFILE)
        request = parse_request("mande para o Otávio no whatsapp web desse perfil: oi")
        assert request is not None
        self.assertEqual((request.contact, request.profile), ("Otávio", CURRENT_PROFILE))

    def test_open_in_current_profile(self) -> None:
        opened: list[str] = []
        flow = WhatsAppDesktop(open_app=lambda _n: None, open_target=lambda _u: None, keys=None, ask_screen=None,
                               open_current=lambda url: opened.append(url) or True)
        self.assertEqual(flow.open_web(CURRENT_PROFILE)["message"], "Feito, senhor.")
        self.assertEqual(opened, ["https://web.whatsapp.com/"])


if __name__ == "__main__":
    unittest.main()
