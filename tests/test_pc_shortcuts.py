"""Atalhos diretos (sem modelo) para janelas, Windows, arquivos, web, agenda e leitura do WhatsApp."""

from __future__ import annotations

import unittest

from brain.pc_shortcuts import match
from brain.router import Intent, IntentRouter
from voice.local_wake import classify, decide, grammar


class PcShortcutTests(unittest.TestCase):
    def test_commands_map_to_the_right_tool(self) -> None:
        cases = {
            "abre as configurações de Bluetooth": ("open_settings", {"page": "Bluetooth"}),
            "coloca o brilho em 60": ("brightness_set", {"percent": 60}),
            "como está o Wi-Fi?": ("wifi_status", {}),
            "tira um print e salva": ("screenshot_save", {}),
            "quais apps eu tenho com adobe?": ("apps_list", {"query": "adobe"}),
            "quais janelas estão abertas?": ("windows_list", {}),
            "mostra a área de trabalho": ("show_desktop", {}),
            "TELEX, minimiza o Chrome": ("window_minimize", {"title": "Chrome"}),
            "maximiza o Excel": ("window_maximize", {"title": "Excel"}),
            "traz o Excel para a frente": ("window_focus", {"title": "Excel"}),
            "coloca o VS Code na esquerda": ("snap_window", {"title": "VS Code", "side": "esquerda"}),
            "o que eu baixei por último?": ("recent_files", {"folder": "downloads"}),
            "cria a pasta Projetos em documentos": ("create_folder", {"name": "Projetos", "parent": "documentos"}),
            "baixa esse PDF: https://ex.com/a.pdf": ("download_file", {"url": "https://ex.com/a.pdf"}),
            "o site https://ex.com está no ar?": ("check_url", {"url": "https://ex.com"}),
            "lê esse site e me resume: https://g1.globo.com/x": ("read_webpage", {"url": "https://g1.globo.com/x"}),
            "lê as últimas mensagens do grupo do trabalho": ("whatsapp_read", {"contact": "trabalho", "group": True}),
            "marque reunião com o João amanhã às 15h": ("calendar_event", {"title": "Reunião com o João", "when": "amanhã às 15h"}),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(match(text), expected)

    def test_other_phrases_are_not_shortcuts(self) -> None:
        for text in ("abre o chrome", "qual é a capital da França?", "me lembre de beber água amanhã às 9h", "coloca a música mais alta", ""):
            with self.subTest(text=text):
                self.assertIsNone(match(text))

    def test_router_sends_settings_to_the_shortcut_not_open_app(self) -> None:
        self.assertEqual(IntentRouter().route("abre as configurações de Bluetooth").intent, Intent.SHORTCUT)


class NameOnlyWakeTests(unittest.TestCase):
    def test_only_the_name_activates(self) -> None:
        self.assertEqual(decide(classify("telex"), False, False), ("call", None))
        self.assertEqual(decide(classify("boa noite telex"), False, False), ("call", None))
        self.assertIsNone(classify("boa noite"))
        self.assertFalse(any(phrase.startswith(("bom dia", "boa tarde", "boa noite")) for phrase in grammar()))


if __name__ == "__main__":
    unittest.main()
