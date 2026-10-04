"""Ajustes 15: TELEX 100% local — cérebro (Ollama), voz (Piper/SAPI), ouvido (Vosk) e conversa sem OpenAI."""

from __future__ import annotations

import array
import io
import json
import os
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from typing import Any
from unittest import mock

from brain.model import ChainModel, ModelAdapter, ModelResponse, NullModel, OllamaModel, default_model
from voice import local_runtime, local_stt, local_tts
from voice.local_session import FRAME_BYTES, Deps, LocalSession, strip_name


class FakeModel(ModelAdapter):
    def __init__(self, text: str = "", error: Exception | None = None) -> None:
        self.text, self.error, self.calls = text, error, 0

    def respond(self, messages: list[dict[str, str]], **kwargs: Any) -> ModelResponse:
        self.calls += 1
        if self.error:
            raise self.error
        return ModelResponse(self.text)


class ChainModelTests(unittest.TestCase):
    def test_falls_back_when_first_fails(self) -> None:
        broken = FakeModel(error=RuntimeError("sem créditos"))
        good = FakeModel("oi")
        chain = ChainModel([broken, good])
        self.assertEqual(chain.respond([]).text, "oi")
        self.assertIn("sem créditos", chain.last_error or "")

    def test_failed_model_rests_then_returns(self) -> None:
        now = [0.0]
        broken, good = FakeModel(error=RuntimeError("x")), FakeModel("ok")
        chain = ChainModel([broken, good], cooldown=60, clock=lambda: now[0])
        chain.respond([])
        chain.respond([])
        self.assertEqual(broken.calls, 1)  # de castigo: não tenta de novo
        now[0] = 61.0
        chain.respond([])
        self.assertEqual(broken.calls, 2)

    def test_all_failing_raises(self) -> None:
        chain = ChainModel([FakeModel(error=RuntimeError("a")), FakeModel(error=ValueError("b"))])
        with self.assertRaises(ValueError):
            chain.respond([])


class OllamaModelTests(unittest.TestCase):
    def fake_urlopen(self, tags: list[str] | None = None, content: str = "Olá!") -> Any:
        def opener(request: Any, timeout: float = 0) -> Any:
            url = request if isinstance(request, str) else request.full_url
            body = {"models": [{"name": name} for name in (tags or [])]} if url.endswith("/api/tags") else {"message": {"content": content}}
            return io.BytesIO(json.dumps(body).encode())

        return opener

    def test_available_needs_model_downloaded(self) -> None:
        model = OllamaModel("qwen2.5:3b", host="localhost:11434")
        with mock.patch("urllib.request.urlopen", self.fake_urlopen(["qwen2.5:3b"])):
            self.assertTrue(model.available())
        with mock.patch("urllib.request.urlopen", self.fake_urlopen(["llama3:8b"])):
            self.assertFalse(model.available())
        with mock.patch("urllib.request.urlopen", side_effect=OSError("fora do ar")):
            self.assertFalse(model.available())

    def test_respond_returns_text(self) -> None:
        model = OllamaModel("qwen2.5:3b")
        with mock.patch("urllib.request.urlopen", self.fake_urlopen(content=" Tudo certo. ")):
            self.assertEqual(model.respond([{"role": "user", "content": "oi"}]).text, "Tudo certo.")
        self.assertEqual(OllamaModel(host="localhost:11434").host, "http://localhost:11434")


class DefaultModelTests(unittest.TestCase):
    def test_no_local_no_key_is_null(self) -> None:
        with mock.patch.dict(os.environ, {"DUQUE_BRAIN": "auto"}, clear=False), mock.patch.object(
            OllamaModel, "available", return_value=False
        ):
            os.environ.pop("OPENAI_API_KEY", None)
            self.assertIsInstance(default_model(), NullModel)

    def test_local_up_is_used_with_openai_as_backup(self) -> None:
        with mock.patch.dict(os.environ, {"DUQUE_BRAIN": "auto", "OPENAI_API_KEY": "sk-teste"}), mock.patch.object(
            OllamaModel, "available", return_value=True
        ):
            model = default_model()
            self.assertIsInstance(model, ChainModel)
            self.assertIsInstance(model.models[0], OllamaModel)  # type: ignore[attr-defined]

    def test_local_only_mode(self) -> None:
        with mock.patch.dict(os.environ, {"DUQUE_BRAIN": "local", "OPENAI_API_KEY": "sk-teste"}):
            self.assertIsInstance(default_model(), OllamaModel)


class VoiceModeTests(unittest.TestCase):
    def test_modes(self) -> None:
        with mock.patch.dict(os.environ, {"DUQUE_VOICE": "auto"}):
            self.assertEqual(local_runtime.voice_mode(True), "openai")
            self.assertEqual(local_runtime.voice_mode(False), "local")
            self.assertEqual(local_runtime.voice_mode(True, openai_blocked=True), "local")
        with mock.patch.dict(os.environ, {"DUQUE_VOICE": "local"}):
            self.assertEqual(local_runtime.voice_mode(True), "local")


class TtsTests(unittest.TestCase):
    def test_clean_for_speech(self) -> None:
        self.assertEqual(local_tts.clean_for_speech("**Feito!** Veja https://x.com 😀\nOk"), "Feito! Veja. Ok.")
        self.assertEqual(local_tts.clean_for_speech("   "), "")

    def test_audio_wav_roundtrip(self) -> None:
        audio = local_tts.Audio(array.array("h", [0, 1000, -1000, 0]).tobytes(), 22050)
        with wave.open(io.BytesIO(audio.to_wav())) as wav:
            self.assertEqual((wav.getnchannels(), wav.getframerate(), wav.getnframes()), (1, 22050, 4))

    def test_piper_engine_runs_exe_with_voice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            voice = Path(tmp) / "pt_BR-teste.onnx"
            voice.write_bytes(b"x")
            Path(str(voice) + ".json").write_text(json.dumps({"audio": {"sample_rate": 16000}}), encoding="utf-8")
            calls: list[Any] = []

            def run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
                calls.append((cmd, kwargs["input"]))
                return subprocess.CompletedProcess(cmd, 0, stdout=b"\x01\x00" * 8, stderr=b"")

            engine = local_tts.PiperEngine(Path("piper.exe"), voice, run=run)
            audio = local_tts.Speaker(engine).synthesize("Olá, Du")
            self.assertEqual(audio.sample_rate, 16000)
            self.assertEqual(len(audio.pcm), 16)
            self.assertIn(str(voice), calls[0][0])
            self.assertEqual(calls[0][1], "Olá, Du.".encode("utf-8"))

    def test_piper_failure_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            voice = Path(tmp) / "v.onnx"
            voice.write_bytes(b"x")
            run = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"boom")  # noqa: E731
            with self.assertRaises(RuntimeError):
                local_tts.PiperEngine(Path("piper.exe"), voice, run=run).synthesize("oi")

    def test_voice_choice_by_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(local_tts, "VOICES_DIR", Path(tmp)):
            (Path(tmp) / "pt_BR-a.onnx").write_bytes(b"x")
            (Path(tmp) / "pt_BR-b.onnx").write_bytes(b"x")
            with mock.patch.dict(os.environ, {"DUQUE_PIPER_VOICE": ""}):
                self.assertEqual(local_tts.find_piper_voice().name, "pt_BR-a.onnx")  # type: ignore[union-attr]
            with mock.patch.dict(os.environ, {"DUQUE_PIPER_VOICE": "pt_BR-b"}):
                self.assertEqual(local_tts.find_piper_voice().name, "pt_BR-b.onnx")  # type: ignore[union-attr]
            with mock.patch.dict(os.environ, {"DUQUE_PIPER_VOICE": "nao-existe"}):
                self.assertIsNone(local_tts.find_piper_voice())
            self.assertEqual(local_tts.list_voices(), ["pt_BR-a", "pt_BR-b"])


class SttTests(unittest.TestCase):
    def test_vosk_transcriber_collects_final_text(self) -> None:
        class Recognizer:
            def __init__(self, model: Any, rate: int) -> None:
                self.chunks = 0

            def AcceptWaveform(self, data: bytes) -> bool:
                self.chunks += 1
                return False

            def FinalResult(self) -> str:
                return json.dumps({"text": "que horas são"})

        transcriber = local_stt.VoskTranscriber(object(), Recognizer)
        self.assertEqual(transcriber.transcribe(b"\0" * 40000), "que horas são")


def loud(level: int = 8000) -> bytes:
    return array.array("h", [level, -level] * (FRAME_BYTES // 4)).tobytes()


def quiet() -> bytes:
    return b"\0" * FRAME_BYTES


class SessionHarness:
    def __init__(self, script: list[bytes], transcripts: list[str], reply: str = "Feito.") -> None:
        self.frames = list(script)
        self.transcripts = list(transcripts)
        self.reply = reply
        self.spoken: list[str] = []
        self.thought: list[str] = []
        self.recorded: list[tuple[str, str]] = []
        self.chimes = 0
        self.muted = 0
        self.deps = Deps(
            read_frame=self.read,
            transcribe=lambda _pcm: self.transcripts.pop(0) if self.transcripts else "",
            synthesize=lambda text: (self.spoken.append(text), local_tts.Audio(b"\x01\x00" * 10, 16000))[1],
            play=lambda _audio: None,
            think=self.think,
            chime=self.chime,
            hud=lambda *_a: None,
            log=lambda _m: None,
            record=lambda role, text: self.recorded.append((role, text)),
            mute_mic=lambda: setattr(self, "muted", self.muted + 1),
        )

    def read(self) -> bytes:
        return self.frames.pop(0) if self.frames else b""

    def think(self, request: str) -> str:
        self.thought.append(request)
        return self.reply

    def chime(self) -> None:
        self.chimes += 1


def speech_then_silence(words_frames: int = 6) -> list[bytes]:
    return [quiet()] * 3 + [loud()] * words_frames + [quiet()] * 20


class LocalSessionTests(unittest.TestCase):
    def test_strip_name_keeps_accents(self) -> None:
        self.assertEqual(strip_name("Telex, que horas são?"), "que horas são")
        self.assertEqual(strip_name("télex abra o chrome"), "abra o chrome")
        self.assertEqual(strip_name("tele x"), "")

    def test_capture_waits_for_speech_and_stops_on_pause(self) -> None:
        harness = SessionHarness(speech_then_silence(), [])
        pcm = LocalSession(harness.deps).capture(8)
        self.assertGreaterEqual(len(pcm), 6 * FRAME_BYTES)
        self.assertLess(len(pcm), 6 * FRAME_BYTES + 20 * FRAME_BYTES)

    def test_capture_returns_empty_when_nobody_talks(self) -> None:
        harness = SessionHarness([quiet()] * 200, [])
        self.assertEqual(LocalSession(harness.deps).capture(2), b"")

    def test_quiet_microphone_is_still_heard(self) -> None:
        harness = SessionHarness([quiet()] * 3 + [loud(3000)] * 6 + [quiet()] * 20, [])  # pico ~0.09, como o seu
        self.assertGreater(len(LocalSession(harness.deps).capture(8)), 0)

    def test_preroll_request_is_answered_aloud(self) -> None:
        harness = SessionHarness([quiet()] * 50, ["telex que horas são"], reply="São dez horas.")
        preroll = b"".join([loud()] * 6 + [quiet()] * 20)
        reason = LocalSession(harness.deps).converse(call=True, preroll=preroll)
        self.assertEqual(reason, "pedido")
        self.assertEqual(harness.thought, ["que horas são"])
        self.assertEqual(harness.spoken, ["São dez horas."])
        self.assertEqual(harness.recorded, [("user", "que horas são"), ("assistant", "São dez horas.")])
        self.assertGreaterEqual(harness.muted, 1)  # microfone fechado enquanto fala

    def test_greeting_speaks_then_goes_to_standby_on_silence(self) -> None:
        harness = SessionHarness([quiet()] * 400, [])
        reason = LocalSession(harness.deps).converse("bom dia telex")
        self.assertEqual(reason, "silêncio")
        self.assertEqual(harness.spoken, ["Bom dia, Du. À sua disposição."])
        self.assertEqual(harness.thought, [])

    def test_name_alone_chimes_then_listens(self) -> None:
        harness = SessionHarness(speech_then_silence() + speech_then_silence() + [quiet()] * 200, ["telex", "toque rock"])
        LocalSession(harness.deps).converse()
        self.assertEqual(harness.chimes, 2)  # ao acordar e depois de "Telex" sozinho
        self.assertEqual(harness.thought, ["toque rock"])  # sem o nome, porque a escuta estava aberta

    def test_question_keeps_listening_without_name(self) -> None:
        harness = SessionHarness(
            speech_then_silence() + speech_then_silence() + [quiet()] * 200, ["telex aumente o volume", "mais um pouco"]
        )
        replies = iter(["O volume está bom?", "Pronto."])
        harness.think = lambda request: (harness.thought.append(request), next(replies))[1]  # type: ignore[method-assign]
        harness.deps.think = harness.think
        reason = LocalSession(harness.deps).converse()
        self.assertEqual(reason, "pedido")
        self.assertEqual(harness.thought, ["aumente o volume", "mais um pouco"])

    def test_sleep_ends_without_thinking(self) -> None:
        harness = SessionHarness(speech_then_silence(), ["repousar telex"])
        self.assertEqual(LocalSession(harness.deps).converse(), "repousar")
        self.assertEqual(harness.thought, [])

    def test_brain_failure_is_spoken_not_fatal(self) -> None:
        harness = SessionHarness(speech_then_silence(), ["telex faça algo"])
        harness.deps.think = lambda _r: (_ for _ in ()).throw(RuntimeError("modelo fora do ar"))
        LocalSession(harness.deps).converse()
        self.assertIn("problema", harness.spoken[0])


class DefaultWiringTests(unittest.TestCase):
    def test_wake_loop_no_longer_requires_openai_key(self) -> None:
        source = (Path(__file__).resolve().parent.parent / "duque_wake_v2.py").read_text(encoding="utf-8")
        self.assertNotIn('raise RuntimeError("OPENAI_API_KEY não encontrada', source)
        self.assertIn("local_voice.run(", source)
        self.assertIn("OPENAI_BLOCKED = True", source)

    def test_setup_script_exists(self) -> None:
        root = Path(__file__).resolve().parent.parent
        script = (root / "preparar_local.bat").read_text(encoding="utf-8", errors="ignore")
        self.assertIn("ollama pull", script)
        self.assertIn("voice.local_tts --baixar", script)


if __name__ == "__main__":
    unittest.main()
