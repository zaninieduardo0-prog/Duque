"""Ajustes 16: voz do Fish Audio opcional, com a voz local sempre de reserva."""

from __future__ import annotations

import array
import io
import os
import struct
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from voice import local_tts
from voice.local_tts import Audio, FallbackEngine, FishEngine, Speaker, parse_wav


def make_wav(samples: list[int], rate: int = 24000, streaming: bool = False) -> bytes:
    pcm = array.array("h", samples).tobytes()
    size = 0xFFFFFFFF if streaming else len(pcm)
    header = b"RIFF" + struct.pack("<I", size) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
    return header + b"data" + struct.pack("<I", size) + pcm


class Engine:
    def __init__(self, name: str, fail: bool = False) -> None:
        self.name, self.fail, self.calls = name, fail, 0

    def synthesize(self, text: str) -> Audio:
        self.calls += 1
        if self.fail:
            raise RuntimeError("recusou")
        return Audio(b"\x01\x00" * 4, 16000)


class ParseWavTests(unittest.TestCase):
    def test_normal_and_streaming_wav(self) -> None:
        for streaming in (False, True):
            audio = parse_wav(make_wav([1, 2, 3, 4], streaming=streaming))
            self.assertEqual((audio.sample_rate, len(audio.pcm)), (24000, 8))

    def test_not_a_wav_is_an_error(self) -> None:
        with self.assertRaises(RuntimeError):
            parse_wav(b"<html>erro</html>")


class FishEngineTests(unittest.TestCase):
    def test_request_uses_key_voice_and_free_model(self) -> None:
        seen: list[Any] = []

        def opener(request: Any, timeout: float = 0) -> Any:
            seen.append(request)
            return io.BytesIO(make_wav([5, 6]))

        audio = FishEngine("chave-teste", "voz123", opener=opener).synthesize("Olá")
        self.assertEqual(len(audio.pcm), 4)
        request = seen[0]
        self.assertEqual(request.full_url, "https://api.fish.audio/v1/tts")
        self.assertEqual(request.get_header("Authorization"), "Bearer chave-teste")
        self.assertEqual(request.get_header("Model"), "s2.1-pro-free")
        self.assertIn(b'"reference_id": "voz123"', request.data)

    def test_refusal_is_an_error(self) -> None:
        def opener(request: Any, timeout: float = 0) -> Any:
            raise OSError("402")

        with self.assertRaises(RuntimeError):
            FishEngine("k", opener=opener).synthesize("oi")


class FallbackTests(unittest.TestCase):
    def test_uses_backup_when_primary_refuses_then_rests(self) -> None:
        now = [0.0]
        primary, backup = Engine("fish", fail=True), Engine("piper")
        engine = FallbackEngine(primary, backup, cooldown=300, clock=lambda: now[0])
        engine.synthesize("a")
        engine.synthesize("b")
        self.assertEqual((primary.calls, backup.calls), (1, 2))  # Fish de castigo: não insiste
        now[0] = 301.0
        engine.synthesize("c")
        self.assertEqual(primary.calls, 2)

    def test_primary_used_when_it_works(self) -> None:
        primary, backup = Engine("fish"), Engine("piper")
        FallbackEngine(primary, backup).synthesize("a")
        self.assertEqual((primary.calls, backup.calls), (1, 0))


class LoadTests(unittest.TestCase):
    def test_without_key_fish_is_never_used(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "FISH_API_KEY"}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(
            local_tts, "find_piper_exe", return_value=None
        ):
            speaker = local_tts.load(lambda _m: None)
            self.assertNotIsInstance(getattr(speaker, "engine", None), (FishEngine, FallbackEngine))

    def test_with_key_fish_has_local_backup(self) -> None:
        # Hermético: a voz local de reserva existe (Piper instalado), seja qual for a
        # máquina. Antes o teste dependia de SAPI (só Windows) ou de um Piper real.
        with mock.patch.dict(os.environ, {"FISH_API_KEY": "k", "DUQUE_TTS": "auto"}), mock.patch.object(
            local_tts, "find_piper_exe", return_value=Path("piper.exe")
        ), mock.patch.object(local_tts, "find_piper_voice", return_value=Path("pt_BR-faber-medium.onnx")):
            speaker = local_tts.load(lambda _m: None)
            assert speaker is not None
            self.assertIsInstance(speaker.engine, FallbackEngine)
            self.assertIn("reserva", speaker.name)

    def test_speaker_cleans_text_for_any_engine(self) -> None:
        engine = Engine("x")
        self.assertEqual(Speaker(engine).synthesize("  ").pcm, b"")
        self.assertEqual(engine.calls, 0)


if __name__ == "__main__":
    unittest.main()
