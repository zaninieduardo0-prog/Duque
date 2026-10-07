"""Autonomia no PC: janelas, Configurações, apps do Menu Iniciar e arquivos."""

from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from computer import apps
from computer.apps import (
    app_match_score,
    build_app_index,
    find_installed_app,
    installed_apps,
    match_app_name,
    resolve_app,
)
from computer.file_tools import FileTools, guard_write, sanitize_filename
from computer.windows_tools import (
    SETTINGS_PAGES,
    WindowTools,
    is_protected_window,
    match_window,
    parse_wlan_interfaces,
    resolve_settings_page,
)


class SettingsPagesTests(unittest.TestCase):
    def test_portuguese_aliases(self) -> None:
        cases = {
            "wifi": "network-wifi", "Wi-Fi": "network-wifi", "bluetooth": "bluetooth", "som": "sound",
            "áudio": "sound", "tela": "display", "bateria": "batterysaver", "energia": "powersleep",
            "Atualizações": "windowsupdate", "aplicativos": "appsfeatures", "notificações": "notifications",
            "privacidade": "privacy", "rede": "network", "impressoras": "printers", "mouse": "mousetouchpad",
            "teclado": "typing", "data e hora": "dateandtime", "personalização": "personalization",
            "papel de parede": "personalization-background", "modo escuro": "colors",
            "armazenamento": "storagesense", "apps padrão": "defaultapps", "padrão": "defaultapps",
            "configurações de som": "sound", "ms-settings:bluetooth": "bluetooth", "network-wifi": "network-wifi",
        }
        for spoken, page in cases.items():
            with self.subTest(spoken=spoken):
                self.assertEqual(resolve_settings_page(spoken), page)

    def test_home_and_unknown(self) -> None:
        self.assertEqual(resolve_settings_page(""), "")
        self.assertEqual(resolve_settings_page("configurações"), "")
        self.assertIsNone(resolve_settings_page("geladeira"))
        self.assertIsNone(resolve_settings_page("network-wifi; calc"))

    def test_unknown_page_lists_options_without_opening(self) -> None:
        with mock.patch("computer.windows_tools._startfile") as opener:
            result = WindowTools().open_settings("geladeira")
        opener.assert_not_called()
        self.assertFalse(result["success"])
        self.assertIn("wifi", result["error"])

    def test_known_page_opens_ms_settings(self) -> None:
        with mock.patch("computer.windows_tools._startfile") as opener:
            result = WindowTools().open_settings("modo escuro")
        opener.assert_called_once_with("ms-settings:colors")
        self.assertEqual(result["uri"], "ms-settings:colors")

    def test_all_pages_are_plain_ids(self) -> None:
        for page in SETTINGS_PAGES.values():
            self.assertRegex(page, r"^[a-z-]*$")


class WindowMatchTests(unittest.TestCase):
    WINDOWS = [
        {"hwnd": 1, "title": "TELEX — NEURAL CORE - Google Chrome", "exe": "chrome.exe"},
        {"hwnd": 2, "title": "Relatório Mensal.xlsx - Excel", "exe": "excel.exe"},
        {"hwnd": 3, "title": "(12) Música relaxante - YouTube - Google Chrome", "exe": "chrome.exe"},
        {"hwnd": 4, "title": "Downloads", "exe": "explorer.exe"},
        {"hwnd": 5, "title": "Sem título - Bloco de Notas", "exe": "notepad.exe"},
    ]

    def pick(self, query: str, **kwargs: bool) -> int | None:
        window = match_window(query, self.WINDOWS, **kwargs)
        return window["hwnd"] if window else None

    def test_title_accent_and_case_insensitive(self) -> None:
        self.assertEqual(self.pick("relatorio mensal"), 2)
        self.assertEqual(self.pick("MUSICA"), 3)
        self.assertEqual(self.pick("bloco de notas"), 5)

    def test_process_name(self) -> None:
        self.assertEqual(self.pick("excel"), 2)
        self.assertEqual(self.pick("notepad"), 5)

    def test_exact_title_wins(self) -> None:
        self.assertEqual(self.pick("downloads"), 4)

    def test_hud_is_never_chosen_by_default(self) -> None:
        self.assertEqual(self.pick("chrome"), 3)
        self.assertIsNone(self.pick("telex"))
        self.assertEqual(self.pick("telex", allow_protected=True), 1)

    def test_no_match(self) -> None:
        self.assertIsNone(self.pick("photoshop"))
        self.assertIsNone(self.pick(""))

    def test_protected_titles(self) -> None:
        self.assertTrue(is_protected_window("TELEX — NEURAL CORE"))
        self.assertTrue(is_protected_window("127.0.0.1:5000 - Google Chrome"))
        self.assertFalse(is_protected_window("YouTube - Google Chrome"))

    def test_close_refuses_hud(self) -> None:
        tools = WindowTools()
        with mock.patch("computer.windows_tools.IS_WINDOWS", True), \
                mock.patch.object(WindowTools, "_windows", return_value=list(self.WINDOWS)):
            result = tools.window_close("telex")
        self.assertFalse(result["success"])
        self.assertIn("TELEX", result["error"])

    def test_wlan_parse_portuguese(self) -> None:
        text = (
            "Há 1 interface no sistema:\n\n"
            "    Nome                   : Wi-Fi\n"
            "    Estado                 : conectado\n"
            "    SSID                   : Casa 5G\n"
            "    BSSID                  : aa:bb:cc:dd:ee:ff\n"
            "    Tipo de rádio          : 802.11ac\n"
            "    Sinal                  : 87%\n"
            "    Perfil                 : Casa 5G\n"
        )
        info = parse_wlan_interfaces(text)
        self.assertEqual(info["ssid"], "Casa 5G")
        self.assertEqual(info["signal"], 87)
        self.assertTrue(info["connected"])
        self.assertEqual(info["interface"], "Wi-Fi")

    def test_wlan_parse_english_disconnected(self) -> None:
        info = parse_wlan_interfaces("    Name : Wi-Fi\n    State : disconnected\n")
        self.assertFalse(info["connected"])
        self.assertNotIn("ssid", info)

    def test_contract(self) -> None:
        for cls in (WindowTools, FileTools):
            names = [spec[0] for spec in cls.SPECS]
            self.assertEqual(set(names), set(cls.RISK))
            for name in names:
                self.assertTrue(callable(getattr(cls, name)))
                self.assertIn(cls.RISK[name], {"low", "medium", "high"})
        self.assertEqual(FileTools.RISK["move_to_trash"], "high")


class StartMenuTests(unittest.TestCase):
    SHORTCUTS = [
        "Excel.lnk", "Word.lnk", "WordPad.lnk", "Visual Studio Code/Visual Studio Code.lnk",
        "Visual Studio Code/Uninstall Visual Studio Code.lnk", "Microsoft Teams.lnk",
        "Python 3.12/Python 3.12 (64-bit).lnk", "Python 3.12/IDLE (Python 3.12 64-bit).lnk",
        "GIMP/GIMP 2.10.lnk", "GIMP/Readme.lnk", "Steam/Steam Support Center.url",
        "Ferramentas/Calculadora Científica.appref-ms", "notas.txt",
    ]

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for item in self.SHORTCUTS:
            path = self.root / item
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x", encoding="utf-8")
        self.roots = [self.root]

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_index_skips_uninstall_readme_interpreters_and_non_shortcuts(self) -> None:
        index = build_app_index(self.roots)
        self.assertIn("Excel", index)
        self.assertIn("Visual Studio Code", index)
        self.assertIn("Calculadora Científica", index)
        for name in index:
            self.assertNotIn("uninstall", name.casefold())
            self.assertNotIn("readme", name.casefold())
            self.assertNotIn("python", name.casefold())
        self.assertNotIn("notas", index)

    def test_fuzzy_matching(self) -> None:
        cases = {
            "excel": "Excel.lnk", "Word": "Word.lnk", "vs code": "Visual Studio Code.lnk",
            "vscode": "Visual Studio Code.lnk", "teams": "Microsoft Teams.lnk", "gimp": "GIMP 2.10.lnk",
            "calculadora cientifica": "Calculadora Científica.appref-ms", "o aplicativo do excel": "Excel.lnk",
        }
        for query, expected in cases.items():
            with self.subTest(query=query):
                found = find_installed_app(query, self.roots)
                self.assertIsNotNone(found)
                self.assertEqual(Path(str(found)).name, expected)

    def test_refuses_paths_interpreters_and_unknown(self) -> None:
        for query in ("python3", "python", r"C:\\x\\Excel.lnk", "../Excel", "geladeira", ""):
            with self.subTest(query=query):
                self.assertIsNone(find_installed_app(query, self.roots))

    def test_score_prefers_exact(self) -> None:
        self.assertGreater(app_match_score("word", "Word"), app_match_score("word", "WordPad"))
        self.assertEqual(match_app_name("word", ["WordPad", "Word"]), "Word")

    def test_installed_apps_filter(self) -> None:
        self.assertEqual(installed_apps("visual", self.roots), ["Visual Studio Code"])
        self.assertIn("Excel", installed_apps("", self.roots))

    def test_resolve_app_falls_back_to_start_menu_shortcut(self) -> None:
        with mock.patch.object(apps, "start_menu_dirs", return_value=self.roots):
            apps.app_index(self.roots, refresh=True)
            command = resolve_app("gimp")
            self.assertIsNotNone(command)
            assert command is not None
            self.assertEqual(command[:4], ["cmd.exe", "/c", "start", ""])
            self.assertEqual(Path(command[4]).name, "GIMP 2.10.lnk")
            # Os cadastrados continuam vencendo; caminhos e interpretadores, recusados.
            self.assertEqual(resolve_app("excel"), apps.KNOWN_APPS["excel"])
            self.assertIsNone(resolve_app("python3"))
            self.assertIsNone(resolve_app(str(self.root / "Excel.lnk")))
            self.assertIsNone(resolve_app("minha calculadora"))  # quem chama acha "calculadora"


class FileToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        (self.base / "docs").mkdir()
        (self.base / "down").mkdir()
        self.tools = FileTools({"documentos": self.base / "docs", "downloads": self.base / "down"})

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_sanitize(self) -> None:
        self.assertEqual(sanitize_filename("lista de compras", ".txt"), "lista de compras.txt")
        self.assertEqual(sanitize_filename("../../etc/passwd"), "etc passwd")
        self.assertEqual(sanitize_filename('a<b>:c"d|e?f*g.md'), "a b c d e f g.md")
        self.assertEqual(sanitize_filename("CON", ".txt"), "_CON.txt")
        self.assertEqual(sanitize_filename("nota.  "), "nota")
        self.assertLessEqual(len(sanitize_filename("x" * 500, ".txt")), 120)
        with self.assertRaises(ValueError):
            sanitize_filename(" / .. ")

    def test_save_append_read(self) -> None:
        saved = self.tools.save_text_file("compras", "arroz\nfeijão")
        self.assertEqual(Path(saved["path"]).name, "compras.txt")
        again = self.tools.save_text_file("compras", "outra coisa")
        self.assertFalse(again["success"])
        self.assertEqual((self.base / "docs" / "compras.txt").read_text(encoding="utf-8"), "arroz\nfeijão")
        self.assertTrue(self.tools.save_text_file("compras", "novo", overwrite=True)["overwritten"])
        self.tools.append_text_file("compras", "café")
        read = self.tools.read_text_file("compras")
        self.assertEqual(read["content"], "novo\ncafé")
        self.assertFalse(read["truncated"])
        self.assertTrue(self.tools.read_text_file("compras", max_chars=2)["truncated"])
        self.assertFalse(self.tools.read_text_file("nao-existe")["success"])

    def test_save_stays_in_folder(self) -> None:
        result = self.tools.save_text_file("../fora", "x")
        self.assertTrue(Path(result["path"]).parent == self.base / "docs")
        self.assertFalse((self.base / "fora.txt").exists())
        self.assertFalse(self.tools.read_text_file("../down/x.txt")["success"])

    def test_refuses_project_source(self) -> None:
        project = Path(__file__).resolve().parents[1]
        tools = FileTools({"documentos": project / "computer"})
        with mock.patch.dict("os.environ", {"DUQUE_ALLOW_SELF_MODIFICATION": "0"}):
            result = tools.save_text_file("hack.py", "x")
            self.assertFalse(result["success"])
            self.assertFalse((project / "computer" / "hack.py").exists())
            self.assertFalse(tools.rename_file(str(project / "computer" / "apps.py"), "x.py")["success"])
            self.assertFalse(tools.move_to_trash(str(project / "computer" / "apps.py"))["success"])
        self.assertTrue((project / "computer" / "apps.py").exists())

    def test_refuses_system_dirs(self) -> None:
        import os

        system = (os.environ.get("SystemRoot") or "C:\\Windows") if os.name == "nt" else "/etc"
        with self.assertRaises(PermissionError):
            guard_write(Path(system) / "x.txt")

    def test_recent_files_and_folder(self) -> None:
        import os
        import time

        for index, name in enumerate(["a.pdf", "b.zip", "c.png"]):
            path = self.base / "down" / name
            path.write_text("x" * (index + 1), encoding="utf-8")
            moment = time.time() - 100 + index * 10
            os.utime(path, (moment, moment))
        result = self.tools.recent_files("downloads", limit=2)
        self.assertEqual([item["name"] for item in result["files"]], ["c.png", "b.zip"])
        created = self.tools.create_folder("Projetos 2026")
        self.assertTrue(Path(created["path"]).is_dir())
        self.assertFalse(self.tools.create_folder("Projetos 2026")["created"])

    def test_rename_same_folder_keeps_extension(self) -> None:
        source = self.base / "docs" / "relatorio.pdf"
        source.write_text("x", encoding="utf-8")
        result = self.tools.rename_file(str(source), "../final")
        self.assertEqual(Path(result["path"]), self.base / "docs" / "final.pdf")
        self.assertFalse(source.exists())
        (self.base / "docs" / "outro.pdf").write_text("y", encoding="utf-8")
        self.assertFalse(self.tools.rename_file("outro.pdf", "final")["success"])

    def test_zip_and_unzip(self) -> None:
        docs = self.base / "docs"
        (docs / "a.txt").write_text("A", encoding="utf-8")
        (docs / "pasta").mkdir()
        (docs / "pasta" / "b.txt").write_text("B", encoding="utf-8")
        zipped = self.tools.zip_files(["a.txt", "pasta"], "pacote")
        self.assertEqual(zipped["files"], 2)
        self.assertTrue(zipped["path"].endswith("pacote.zip"))
        self.assertFalse(self.tools.zip_files(["a.txt"], "pacote")["success"])  # não sobrescreve
        out = self.tools.unzip_file(zipped["path"])
        dest = Path(out["path"])
        self.assertEqual((dest / "a.txt").read_text(encoding="utf-8"), "A")
        self.assertEqual((dest / "pasta" / "b.txt").read_text(encoding="utf-8"), "B")
        second = self.tools.unzip_file(zipped["path"])
        self.assertNotEqual(second["path"], out["path"])

    def test_unzip_refuses_zip_slip(self) -> None:
        for evil in ("../evil.txt", "/abs/evil.txt", "C:/evil.txt", "ok/../../evil.txt"):
            with self.subTest(evil=evil):
                archive = self.base / "docs" / "mal.zip"
                archive.unlink(missing_ok=True)
                with zipfile.ZipFile(archive, "w") as handle:
                    handle.writestr("bom.txt", "ok")
                    handle.writestr(evil, "mal")
                result = self.tools.unzip_file(str(archive), str(self.base / "out"))
                self.assertFalse(result["success"])
                self.assertFalse((self.base / "evil.txt").exists())
                self.assertFalse((self.base / "out" / "bom.txt").exists())  # nada extraído

    def test_trash_requires_windows(self) -> None:
        target = self.base / "docs" / "lixo.txt"
        target.write_text("x", encoding="utf-8")
        with mock.patch("computer.file_tools.IS_WINDOWS", False):
            with self.assertRaises(RuntimeError):
                self.tools.move_to_trash(str(target))
        self.assertTrue(target.exists())


if __name__ == "__main__":
    unittest.main()
