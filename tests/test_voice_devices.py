from __future__ import annotations

import unittest

from voice.devices import match_input_device, pick_wake_device

DEVICES = ["Headset (Buds Core de Eduardo Hands-Free AG Audio)", "Grupo de microfones (Realtek(R) Audio)"]


class DeviceTests(unittest.TestCase):
    def test_avoids_bluetooth_hands_free(self) -> None:
        """Regressão: usar o microfone do fone Bluetooth deixava o Du sem ouvir nada."""
        index, reason = pick_wake_device(DEVICES, env={})
        self.assertEqual(index, 1)
        self.assertIn("Bluetooth", reason)

    def test_explicit_choice_wins(self) -> None:
        self.assertEqual(pick_wake_device(DEVICES, env={"DUQUE_WAKE_MIC": "0"})[0], 0)
        self.assertEqual(pick_wake_device(DEVICES, env={"DUQUE_MIC": "1"})[0], 1)

    def test_only_bluetooth_available(self) -> None:
        self.assertEqual(pick_wake_device(DEVICES[:1], env={})[0], 0)
        self.assertEqual(pick_wake_device([], env={})[0], -1)

    def test_matches_same_microphone_in_sounddevice(self) -> None:
        sd_devices = [
            {"name": "Mapeador de som da Microsoft - Input", "max_input_channels": 2},
            {"name": "Headset (Buds Core de Eduardo Hands-Free AG Audio)", "max_input_channels": 1},
            {"name": "Grupo de microfones (Realtek(R) Au", "max_input_channels": 2},
            {"name": "Alto-falantes (Realtek(R) Audio)", "max_input_channels": 0},
        ]
        self.assertEqual(match_input_device(DEVICES[1], sd_devices), 2)
        self.assertIsNone(match_input_device("", sd_devices))
        self.assertIsNone(match_input_device("Microfone inexistente", sd_devices))


if __name__ == "__main__":
    unittest.main()
