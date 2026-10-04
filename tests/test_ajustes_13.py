"""Ajustes 13: dois bipes, início oculto com o Windows e autoteste da voz."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class SelftestHelperTests(unittest.TestCase):
    def test_bar_and_rms(self) -> None:
        from voice import selftest

        self.assertIn("0.000", selftest._bar(0.0))
        self.assertTrue(selftest._bar(0.2).startswith("[####"))

    @unittest.skipUnless(importlib.util.find_spec("numpy") is not None, "precisa do numpy")
    def test_rms(self) -> None:
        import numpy as np

        from voice import selftest

        self.assertEqual(selftest._rms(np.zeros(100, dtype="int16")), 0.0)
        self.assertGreater(selftest._rms(np.full(100, 10000, dtype="int16")), 0.2)

    def test_run_without_microphone_is_graceful(self) -> None:
        from unittest import mock

        from voice import selftest

        logged: list[str] = []
        # Sem pvrecorder/numpy, run() deve registrar a falha e não quebrar.
        with mock.patch.dict("sys.modules", {"pvrecorder": None}):
            report = selftest.run(seconds=0.0, log=logged.append)
        self.assertFalse(report["ok"])
        self.assertTrue(any("micro" in line.lower() for line in logged))


class StartHiddenTests(unittest.TestCase):
    def test_launcher_has_hidden_mode(self) -> None:
        source = (ROOT / "duque.py").read_text(encoding="utf-8")
        self.assertIn("def start_hidden()", source)
        self.assertIn("DUQUE_START_HIDDEN", source)
        # No modo oculto, open_interface não abre o HUD no boot.
        self.assertIn("if start_hidden():", source)

    def test_voice_opens_interface_on_activation(self) -> None:
        source = (ROOT / "duque_wake_v2.py").read_text(encoding="utf-8")
        self.assertIn("def abrir_interface_na_ativacao()", source)
        self.assertIn("abrir_interface_na_ativacao()", source.split("def abrir_interface_na_ativacao")[1])

    def test_startup_files_exist(self) -> None:
        for name in ("TELEX_oculto.vbs", "iniciar_com_windows.bat", "parar_inicio_windows.bat"):
            self.assertTrue((ROOT / name).exists(), name)
        self.assertIn("DUQUE_START_HIDDEN", (ROOT / "TELEX_oculto.vbs").read_text(encoding="utf-8", errors="ignore"))
        self.assertIn("Startup", (ROOT / "iniciar_com_windows.bat").read_text(encoding="utf-8", errors="ignore"))


@unittest.skipUnless(
    all(importlib.util.find_spec(n) for n in ("numpy", "sounddevice", "agents", "openwakeword")),
    "runtime de voz exige os pacotes de áudio",
)
class ChimeTests(unittest.TestCase):
    def test_two_distinct_tones(self) -> None:
        import duque_wake_v2 as runtime

        listen = runtime.chime_audio(runtime.CHIME_LISTEN)
        done = runtime.chime_audio(runtime.CHIME_DONE)
        self.assertGreater(len(listen), 2000)
        self.assertGreater(len(done), 2000)
        self.assertNotEqual(listen, done)  # sons diferentes: ouvir vs executar

    def test_play_helpers_exist(self) -> None:
        import duque_wake_v2 as runtime

        self.assertTrue(callable(runtime.play_chime))
        self.assertTrue(callable(runtime.play_done))


if __name__ == "__main__":
    unittest.main()
