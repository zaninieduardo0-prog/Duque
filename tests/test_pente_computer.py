"""Pente fino de computer/: regressões dos bugs de ações duplicadas, janelas a mais e falhas falsas."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from computer.apps import PROCESS_NAMES, resolve_app
from computer.code_tools import CodeTools
from computer.composite_analyzer import CompositeScreenAnalyzer
from computer.controller import ComputerController, shell_target
from computer.perception import Perception, ScreenCapture
from computer.screen_tools import ScreenTools
from computer.system_tools import SystemTools, windows_command_line
from computer.tools import ComputerTools
from computer.verification import Observation, Verification, VerificationStatus, compare
from computer.verification_tools import VerificationTools, screen_text
from computer.verified_ui import VerifiedScreenActions
from computer.windows_ui import key_stroke, text_units
from computer.workspace import PROJECT_ROOT, Workspace, is_project_source


class FakeImage:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def tobytes(self) -> bytes:
        return self.data


class SequenceBackend:
    """Devolve as telas em ordem (a última se repete)."""

    def __init__(self, frames: list[bytes]) -> None:
        self.frames = list(frames)
        self.captures = 0

    def capture(self) -> ScreenCapture:
        self.captures += 1
        data = self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]
        return ScreenCapture(FakeImage(data), 10, 10)


class CountingAnalyzer:
    def __init__(self, result: dict[str, Any] | None = None) -> None:
        self.calls = 0
        self.result = result or {"status": "ok"}

    def analyze(self, capture: ScreenCapture) -> dict[str, Any]:
        self.calls += 1
        return self.result


def verification(frames: list[bytes], analyzer: Any = None) -> Verification:
    return Verification(
        Perception(SequenceBackend(frames), analyzer=analyzer), settle_seconds=1.0, poll_seconds=0.0,
        sleep=lambda _s: None,
    )


class VerificationTests(unittest.TestCase):
    def test_snapshot_does_not_run_analysis_until_needed(self) -> None:
        """Regressão: cada clique rodava OCR/visão no "antes" e no "depois"."""
        analyzer = CountingAnalyzer()
        observation = verification([b"a"], analyzer).snapshot()
        self.assertEqual(analyzer.calls, 0)
        self.assertEqual(observation.description["visual_analysis"], {"status": "ok"})  # type: ignore[index]
        observation.description  # noqa: B018 — cacheado
        self.assertEqual(analyzer.calls, 1)

    def test_waits_for_the_screen_to_react(self) -> None:
        """Regressão: o "depois" era tirado na hora e dava "nada mudou" falso (ação repetida)."""
        check = verification([b"a", b"a", b"a", b"b"])
        before = check.snapshot()
        result = check.verify_change(before)
        self.assertTrue(result.changed)

    def test_gives_up_after_timeout(self) -> None:
        clock = iter([0.0, 0.5, 2.0, 3.0, 4.0])
        check = Verification(Perception(SequenceBackend([b"a"])), settle_seconds=1.0, sleep=lambda _s: None,
                             clock=lambda: next(clock))
        self.assertFalse(check.verify_change(check.snapshot()).changed)

    def test_capture_failure_is_not_reported_as_no_change(self) -> None:
        class Broken:
            def capture(self) -> ScreenCapture:
                raise RuntimeError("sem Pillow")

        check = Verification(Perception(Broken()))
        before = check.snapshot()
        result = compare(before, check.snapshot())
        self.assertEqual(result.status, VerificationStatus.FAILED)
        self.assertTrue(result.changed)  # o executor não deve repetir a ação por isso

    def test_observation_with_explicit_description(self) -> None:
        self.assertEqual(Observation(1, 1, "x", description={"a": 1}).description, {"a": 1})


class ScreenToolsTests(unittest.TestCase):
    def test_composite_status_reflects_sources(self) -> None:
        failing = CountingAnalyzer({"status": "failed"})
        ok = CountingAnalyzer({"status": "ok"})
        self.assertEqual(CompositeScreenAnalyzer(failing).analyze(ScreenCapture(None, 1, 1))["status"], "failed")
        self.assertEqual(CompositeScreenAnalyzer(failing, ok).analyze(ScreenCapture(None, 1, 1))["status"], "ok")

    def test_vision_payload_inside_composite(self) -> None:
        """Regressão: procurava a visão no nível errado e nunca achava os elementos."""
        vision = {"status": "ok", "elements": [{"text": "Enviar", "x": 10, "y": 20, "width": 40, "height": 10, "confidence": 0.9}]}
        description = {"origin": {"x": -1920, "y": 0}, "visual_analysis": {"status": "ok", "ModelVisionAnalyzer": vision}}
        self.assertIs(ScreenTools._vision_payload(description), vision)
        tools = ScreenTools(mock.Mock(snapshot=lambda: Observation(1, 1, "f", description=description)))
        found = tools.find("enviar")
        self.assertEqual(found["click_point"], {"x": 30 - 1920, "y": 25})  # origem da área de trabalho virtual

    def test_screen_text_reads_nested_ocr(self) -> None:
        description = {"visual_analysis": {"status": "ok", "WindowsScreenAnalyzer": {"status": "ok", "ocr": {"status": "ok", "text": "Olá Mundo"}}}}
        self.assertEqual(screen_text(description), ("Olá Mundo", "ok"))

    def test_absent_text_is_an_answer_not_an_error(self) -> None:
        description = {"visual_analysis": {"status": "ok", "ocr": {"status": "ok", "text": "outra coisa"}}}
        tools = VerificationTools(mock.Mock(snapshot=lambda: Observation(1, 1, "f", description=description)))
        result = tools.screen_contains_text("Enviar")
        self.assertFalse(result["found"])
        self.assertNotIn("success", result)
        disabled = {"visual_analysis": {"status": "ok", "ocr": {"status": "disabled"}}}
        tools = VerificationTools(mock.Mock(snapshot=lambda: Observation(1, 1, "f", description=disabled)))
        self.assertFalse(tools.screen_contains_text("x")["success"])

    def test_click_text_never_raises_after_clicking(self) -> None:
        """Regressão: levantava erro DEPOIS do clique e o agente clicava de novo."""
        vision = {"status": "ok", "elements": [{"text": "OK", "x": 0, "y": 0, "width": 10, "height": 10, "confidence": 0.9}]}
        check = verification([b"same"], CountingAnalyzer(vision))
        controller = mock.Mock()
        result = VerifiedScreenActions(controller, check).click_text("OK")
        controller.click.assert_called_once_with(5, 5)
        self.assertTrue(result["clicked"])
        self.assertEqual(result["verification"]["status"], "not_changed")


class KeyboardTests(unittest.TestCase):
    def test_punctuation_is_not_mapped_to_control_keys(self) -> None:
        """Regressão: "," virava Print Screen, "." virava Delete e "/" virava Help."""
        self.assertEqual(key_stroke(","), (0xBC, False))
        self.assertEqual(key_stroke("."), (0xBE, False))
        self.assertEqual(key_stroke("/"), (0xBF, False))
        self.assertEqual(key_stroke("?"), (0xBF, True))
        self.assertEqual(key_stroke("a"), (0x41, False))
        self.assertEqual(key_stroke("Enter"), (0x0D, False))
        self.assertEqual(key_stroke("f11"), (0x7A, False))
        self.assertEqual(key_stroke("/", scan=lambda _c: 0xC1), (0xC1, False))  # ABNT2
        with self.assertRaises(ValueError):
            key_stroke("tecla-inventada")

    def test_text_plan_keeps_accents_and_does_not_send_on_newline(self) -> None:
        plan = text_units("ação\n😀")
        self.assertEqual([kind for kind, _ in plan], ["unicode"] * 4 + ["shift_enter"] + ["unicode"] * 2)
        self.assertEqual(plan[1], ("unicode", ord("ç")))


class AppsTests(unittest.TestCase):
    def test_only_known_apps(self) -> None:
        """Regressão: qualquer executável do PATH abria como "app" (risco baixo, sem confirmação)."""
        self.assertIsNone(resolve_app("python3"))
        self.assertIsNone(resolve_app(r"C:\\Windows\\System32\\cmd.exe"))
        self.assertIsNotNone(resolve_app("Spotify."))
        self.assertNotIn("explorer", PROCESS_NAMES)  # nunca fechar/consultar o shell do Windows

    def test_cmd_start_becomes_shell_open(self) -> None:
        self.assertEqual(shell_target(["cmd.exe", "/c", "start", "", "spotify:"]), "spotify:")
        self.assertIsNone(shell_target(["notepad.exe"]))

    def test_already_running_app_is_focused_not_launched_again(self) -> None:
        controller = mock.Mock()
        tools = ComputerTools(controller=controller)
        tools.is_app_running = lambda name: {"running": True}  # type: ignore[method-assign]
        with mock.patch("platform.system", return_value="Windows"), \
                mock.patch("computer.windows_focus.focus_process_window", return_value=True) as focus:
            result = tools.open_app("spotify")
        controller.launch.assert_not_called()
        focus.assert_called_once()
        self.assertTrue(result["already_running"])

    def test_open_url_verified_opens_only_once(self) -> None:
        """Regressão: sem ver o título a tempo, abria o site DE NOVO (aba duplicada)."""
        controller = ComputerController()
        with mock.patch.object(controller, "open_url") as open_url, \
                mock.patch("computer.windows_focus.IS_WINDOWS", True), \
                mock.patch("computer.windows_focus.focus_site", return_value=False), \
                mock.patch("computer.windows_focus.wait_for_window", return_value=False), \
                mock.patch("os.startfile", create=True) as startfile:
            self.assertFalse(controller.open_url_verified("https://www.youtube.com", "YouTube", timeout=0))
        open_url.assert_called_once()
        startfile.assert_not_called()

    def test_open_path_never_runs_programs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("setup.exe", "script.BAT", "atalho.lnk"):
                target = Path(tmp) / name
                target.write_text("x")
                with self.subTest(name=name), self.assertRaises(PermissionError):
                    ComputerTools(controller=mock.Mock()).open_path(str(target))

    def test_open_folder_only_opens_folders(self) -> None:
        from computer.assistant_tools import AssistantTools

        opened: list[str] = []
        tools = AssistantTools(open_target=opened.append)
        with tempfile.TemporaryDirectory() as tmp:
            program = Path(tmp) / "virus.exe"
            program.write_text("x")
            self.assertIs(tools.open_folder(str(program)).get("success"), False)
            tools.open_folder(tmp)
        self.assertEqual(opened, [tmp])


class SystemToolsTests(unittest.TestCase):
    def test_secrets_are_never_returned(self) -> None:
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-segredo", "DUQUE_CITY": "Piracicaba"}):
            tools = SystemTools()
            self.assertIsNone(tools.environment("OPENAI_API_KEY")["value"])
            self.assertTrue(tools.environment("OPENAI_API_KEY")["exists"])
            self.assertEqual(tools.environment("DUQUE_CITY")["value"], "Piracicaba")
            self.assertNotIn("OPENAI_API_KEY", tools.environment()["variables"])

    def test_read_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            big = Path(tmp) / "big.txt"
            big.write_bytes(b"x" * 5000)
            result = SystemTools().read_any_file(str(big), max_bytes=100)
        self.assertEqual(result["bytes"], 100)
        self.assertTrue(result["truncated"])

    def test_copy_into_itself_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "pasta"
            source.mkdir()
            with self.assertRaises(ValueError):
                SystemTools().copy_path(str(source), str(source / "copia"))

    def test_does_not_kill_itself(self) -> None:
        with self.assertRaises(PermissionError):
            SystemTools().kill_process(os.getpid())

    def test_project_source_is_protected(self) -> None:
        """Só a Forja muda o código do TELEX (cópia isolada, testes e rollback)."""
        with mock.patch.dict(os.environ, {"DUQUE_ALLOW_SELF_MODIFICATION": "0"}):
            with self.assertRaises(PermissionError):
                SystemTools().write_any_file(str(PROJECT_ROOT / "computer" / "x_teste.py"), "quebrado")
            with self.assertRaises(PermissionError):
                CodeTools(Workspace(PROJECT_ROOT)).write_file("servidor.py", "quebrado")
        self.assertFalse((PROJECT_ROOT / "computer" / "x_teste.py").exists())
        self.assertTrue(is_project_source(PROJECT_ROOT / "brain" / "x.py"))
        self.assertFalse(is_project_source(PROJECT_ROOT / "duque_data" / "x.json"))
        self.assertFalse(is_project_source(Path(tempfile.gettempdir()) / "x.py"))

    @unittest.skipIf(sys.platform.startswith("win"), "usa /bin/sh")
    def test_run_command_timeout_kills_and_reports(self) -> None:
        result = SystemTools().run_command("sleep 30", timeout=1)
        self.assertFalse(result["success"])
        self.assertTrue(result["timed_out"])

    def test_windows_command_line_keeps_quotes(self) -> None:
        self.assertEqual(windows_command_line('dir "C:\\Program Files"'), 'cmd.exe /d /s /c "dir "C:\\Program Files""')


class CodeToolsTests(unittest.TestCase):
    def test_listing_skips_venv_and_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for name in (".git/config", ".venv/lib/x.py", "__pycache__/a.pyc", "src/a.py"):
                path = Path(tmp) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("x")
            self.assertEqual(Workspace(tmp).list_files(), [str(Path("src") / "a.py")])

    def test_git_never_prompts_and_adds_only_tracked(self) -> None:
        calls: list[tuple[list[str], dict[str, str] | None]] = []

        def fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            calls.append((args, kwargs.get("env")))
            return subprocess.CompletedProcess(args, 0, "", "")

        with tempfile.TemporaryDirectory() as tmp, mock.patch("computer.code_tools.run_quiet", side_effect=fake_run):
            CodeTools(Workspace(tmp)).git_commit("teste")
        self.assertEqual(calls[0][0], ["git", "add", "-u"])
        self.assertEqual((calls[0][1] or {}).get("GIT_TERMINAL_PROMPT"), "0")
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            CodeTools(Workspace(tmp)).git_push("--force")


class WhatsAppFocusTests(unittest.TestCase):
    def test_no_typing_when_window_cannot_be_focused(self) -> None:
        """Sem foco, as teclas (e o Enter que envia) iriam para outra janela."""
        from computer.whatsapp_flow import WhatsAppDesktop

        keys = mock.Mock()
        flow = WhatsAppDesktop(
            open_app=lambda _n: {"opened": True}, open_target=lambda _u: None, keys=keys,
            ask_screen=lambda _q: "Maria", focus=lambda _f: False, sleep=lambda _s: None,
        )
        result = flow.whatsapp_send("Maria", "oi")
        self.assertFalse(result["success"])
        keys.type_text.assert_not_called()
        keys.press.assert_not_called()

    def test_web_fallback_uses_web_search(self) -> None:
        from computer.whatsapp_flow import WhatsAppDesktop

        keys = mock.Mock()
        flow = WhatsAppDesktop(
            open_app=lambda _n: {"opened": True, "web": True}, open_target=lambda _u: None, keys=keys,
            ask_screen=lambda _q: "Maria", sleep=lambda _s: None,
        )
        flow.whatsapp_send("Maria", "oi", send=False)
        keys.hotkey.assert_any_call("ctrl", "alt", "/")
        self.assertNotIn(mock.call("ctrl", "f"), keys.hotkey.call_args_list)


if __name__ == "__main__":
    unittest.main()
