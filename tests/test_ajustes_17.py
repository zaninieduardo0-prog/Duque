"""Ajustes 17: estilo de voz (grave, calma, firme) e pronúncia correta."""

from __future__ import annotations

import array
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from voice import local_tts
from voice.local_tts import Audio, apply_style, current_style, fix_pronunciation


class StyleTests(unittest.TestCase):
    def test_default_is_calm_and_deep(self) -> None:
        with mock.patch.dict(os.environ, {"DUQUE_VOICE_STYLE": "", "DUQUE_VOICE_PITCH": "", "DUQUE_VOICE_SPEED": ""}):
            style = current_style()
        self.assertGreater(style["length_scale"], 1.0)  # mais devagar
        self.assertLess(style["pitch"], 0.0)  # mais grave

    def test_env_overrides(self) -> None:
        with mock.patch.dict(os.environ, {"DUQUE_VOICE_STYLE": "padrao", "DUQUE_VOICE_PITCH": "-4", "DUQUE_VOICE_SPEED": "0.5"}):
            style = current_style()
        self.assertEqual(style["pitch"], -4.0)
        self.assertEqual(style["length_scale"], 2.0)
        with mock.patch.dict(os.environ, {"DUQUE_VOICE_PITCH": "abc"}):
            self.assertIsInstance(current_style()["pitch"], float)  # valor ruim não quebra

    def test_piper_receives_style_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            voice = Path(tmp) / "v.onnx"
            voice.write_bytes(b"x")
            Path(str(voice) + ".json").write_text(json.dumps({"audio": {"sample_rate": 22050}}), encoding="utf-8")
            seen: list[list[str]] = []

            def run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
                seen.append(cmd)
                return subprocess.CompletedProcess(cmd, 0, stdout=b"\x01\x00" * 8, stderr=b"")

            with mock.patch.dict(os.environ, {"DUQUE_VOICE_STYLE": "firme", "DUQUE_VOICE_SPEED": ""}):
                local_tts.PiperEngine(Path("piper.exe"), voice, run=run).synthesize("oi")
        self.assertIn("--length_scale", seen[0])
        self.assertIn("--sentence_silence", seen[0])

    @unittest.skipUnless(
        importlib.util.find_spec("numpy") is not None and importlib.util.find_spec("pedalboard") is not None,
        "o estilo de voz usa numpy + pedalboard (sem eles o áudio sai como veio, de propósito)",
    )
    def test_apply_style_keeps_length_and_changes_sound(self) -> None:
        samples = array.array("h", [int(8000 * (1 if (i // 20) % 2 else -1)) for i in range(22050)])
        audio = Audio(samples.tobytes(), 22050)
        out = apply_style(audio, STYLE_GRAVE)
        self.assertEqual(len(out.pcm), len(audio.pcm))
        self.assertNotEqual(out.pcm, audio.pcm)

    def test_neutral_style_leaves_audio_alone(self) -> None:
        audio = Audio(b"\x01\x00" * 100, 22050)
        self.assertIs(apply_style(audio, local_tts.STYLES["padrao"]), audio)


STYLE_GRAVE = local_tts.STYLES["grave"]


class PronunciationTests(unittest.TestCase):
    def test_known_words(self) -> None:
        said = fix_pronunciation("abra o YouTube, o Telex e 50%")
        self.assertIn("iutiúbi", said)
        self.assertIn("télex", said)
        self.assertIn("por cento", said)

    def test_does_not_touch_inside_words(self) -> None:
        self.assertEqual(fix_pronunciation("telexes"), "telexes")

    def test_user_dictionary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "duque_data").mkdir()
            (Path(tmp) / "duque_data" / "pronuncia.txt").write_text("# comentário\nEmbralan=embralã\n", encoding="utf-8")
            with mock.patch.object(local_tts, "ROOT", Path(tmp)):
                self.assertEqual(fix_pronunciation("na Embralan"), "na embralã")


if __name__ == "__main__":
    unittest.main()
