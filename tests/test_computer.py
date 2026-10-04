from __future__ import annotations

import os
import unittest
from pathlib import Path
from typing import Any

from brain.vision import NullVisionAdapter, VisionAdapter, VisionResponse
from computer.apps import KNOWN_APPS, PROCESS_NAMES, resolve_app
from computer.code_tools import CodeTools
from computer.composite_analyzer import CompositeScreenAnalyzer
from computer.model_vision_analyzer import ModelVisionAnalyzer
from computer.perception import ScreenCapture
from computer.screen_tools import ScreenTools
from computer.system_tools import SystemTools
from computer.tools import ComputerTools
from computer.verification import Observation, Verification, VerificationStatus
from computer.verification_tools import VerificationTools
from computer.verified_ui import VerifiedScreenActions
from computer.windows_ui import KeySpec, _virtual_key
from computer.workspace import Workspace
from tests.helpers import TempDirTestCase


class AppResolutionTests(unittest.TestCase):
    def test_normalizes_articles_case_and_punctuation(self) -> None:
        self.assertEqual(resolve_app("  O Bloco de Notas. "), KNOWN_APPS["bloco de notas"])
        self.assertEqual(resolve_app("a calculadora!"), KNOWN_APPS["calculadora"])
        self.assertEqual(resolve_app("Chrome"), KNOWN_APPS["chrome"])

    def test_rejects_paths_and_unknown_programs(self) -> None:
        for name in ("C:\\Windows\\System32\\cmd.exe", "../calc", "/bin/sh", "whatsapp:", "python", "sh"):
            with self.subTest(name=name):
                self.assertIsNone(resolve_app(name))

    def test_explorer_is_not_closable(self) -> None:
        self.assertNotIn("explorer", PROCESS_NAMES)
        self.assertNotIn("explorador", PROCESS_NAMES)


class _RecordingController:
    def __init__(self) -> None:
        self.opened: list[Any] = []

    def open_path(self, path: Any) -> None:
        self.opened.append(path)


class OpenPathTests(TempDirTestCase):
    def test_refuses_executables_and_scripts(self) -> None:
        controller = _RecordingController()
        tools = ComputerTools(controller=controller)  # type: ignore[arg-type]
        for name in ("x.exe", "x.BAT", "x.ps1", "atalho.lnk", "x.vbs"):
            target = self.tmp / name
            target.write_text("", encoding="utf-8")
            with self.subTest(name=name), self.assertRaises(PermissionError):
                tools.open_path(str(target))
        self.assertEqual(controller.opened, [])

    def test_opens_documents_and_folders(self) -> None:
        controller = _RecordingController()
        tools = ComputerTools(controller=controller)  # type: ignore[arg-type]
        document = self.tmp / "nota.txt"
        document.write_text("oi", encoding="utf-8")
        self.assertTrue(tools.open_path(str(document))["opened"])
        self.assertTrue(tools.open_path(str(self.tmp))["opened"])
        self.assertEqual(len(controller.opened), 2)


class WorkspaceProtectionTests(TempDirTestCase):
    def test_git_and_env_are_protected(self) -> None:
        workspace = Workspace(self.tmp / "ws")
        for path in (".git/config", "sub/.git/HEAD", ".env", "app/.env.local"):
            with self.subTest(path=path), self.assertRaises(PermissionError):
                workspace.write(path, "x")

    def _duque_project(self) -> Path:
        root = self.tmp / "duque"
        (root / "forge").mkdir(parents=True)
        (root / "core").mkdir()
        (root / "duque.py").write_text("# main\n", encoding="utf-8")
        (root / "core" / "security.py").write_text("NIVEL = 1\n", encoding="utf-8")
        return root

    def test_duque_source_is_protected(self) -> None:
        workspace = Workspace(self._duque_project())
        for path in ("core/security.py", "computer/novo.py", "duque.py", "outro.py", ".github/workflows/ci.yml"):
            with self.subTest(path=path), self.assertRaises(PermissionError):
                workspace.write(path, "x")
        with self.assertRaises(PermissionError):
            workspace.delete("core/security.py")
        # Arquivos fora do código-fonte continuam editáveis.
        self.assertTrue(workspace.write("notas/ideias.md", "x").created)

    def test_forge_can_opt_in(self) -> None:
        workspace = Workspace(self._duque_project(), allow_self_modification=True)
        self.assertTrue(workspace.write("core/security.py", "NIVEL = 2\n").changed)

    def test_write_does_not_crash_on_non_utf8_file(self) -> None:
        workspace = Workspace(self.tmp / "ws")
        (workspace.root / "latin.txt").write_bytes("ação".encode("latin-1"))
        self.assertTrue(workspace.write("latin.txt", "ação").changed)

    def test_list_files_prunes_noise(self) -> None:
        workspace = Workspace(self.tmp / "ws")
        for path in (".git/HEAD", "node_modules/x/i.js", "__pycache__/a.pyc", ".venv/bin/python", "duque_data/db.sqlite"):
            target = workspace.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("x", encoding="utf-8")
        workspace.write("src/main.py", "x")
        self.assertEqual(workspace.list_files(), [os.path.join("src", "main.py")])


class _FakeVerification:
    def __init__(self, description: dict[str, Any]) -> None:
        self.description = description

    def snapshot(self) -> Observation:
        return Observation(10, 10, "abc", description=self.description)


def _composite(local: dict[str, Any] | None = None, vision: dict[str, Any] | None = None) -> dict[str, Any]:
    analysis: dict[str, Any] = {"status": "ok", "sources": []}
    if local is not None:
        analysis["WindowsScreenAnalyzer"] = local
    if vision is not None:
        analysis["ModelVisionAnalyzer"] = vision
    return {"source": "screen", "width": 10, "height": 10, "visual_analysis": analysis}


def _element(text: str, confidence: float = 0.9, x: int = 0) -> dict[str, Any]:
    return {"type": "button", "text": text, "x": x, "y": 0, "width": 10, "height": 10, "confidence": confidence}


class ScreenFindTests(unittest.TestCase):
    def test_vision_payload_found_inside_composite(self) -> None:
        vision = {"status": "ok", "elements": []}
        self.assertIs(ScreenTools._vision_payload(_composite(local={"status": "ok"}, vision=vision)), vision)
        direct = {"visual_analysis": {"status": "ok", "elements": []}}
        self.assertEqual(ScreenTools._vision_payload(direct)["status"], "ok")
        self.assertEqual(ScreenTools._vision_payload(_composite(local={"status": "ok"}))["status"], "unavailable")

    def test_prefers_exact_label_over_substring(self) -> None:
        vision = {"status": "ok", "elements": [_element("Salvar como", 0.95, x=0), _element("Salvar", 0.9, x=50)]}
        tools = ScreenTools(_FakeVerification(_composite(vision=vision)))  # type: ignore[arg-type]
        self.assertEqual(tools.find("salvar")["element"]["x"], 50)

    def test_substring_requires_word_boundary(self) -> None:
        vision = {"status": "ok", "elements": [_element("Abrir arquivo")]}
        tools = ScreenTools(_FakeVerification(_composite(vision=vision)))  # type: ignore[arg-type]
        self.assertEqual(tools.find("arquivo")["element"]["text"], "Abrir arquivo")
        with self.assertRaises(RuntimeError):
            tools.find("rir")


class ScreenContainsTextTests(unittest.TestCase):
    def _tools(self, description: dict[str, Any]) -> VerificationTools:
        return VerificationTools(_FakeVerification(description))  # type: ignore[arg-type]

    def test_direct_ocr_shape(self) -> None:
        description = {"visual_analysis": {"status": "ok", "ocr": {"status": "ok", "text": "Olá Mundo"}}}
        self.assertTrue(self._tools(description).screen_contains_text("olá  mundo")["found"])

    def test_not_found_returns_false_instead_of_raising(self) -> None:
        description = _composite(local={"status": "ok", "ocr": {"status": "ok", "text": "Arquivo"}})
        result = self._tools(description).screen_contains_text("Salvar")
        self.assertFalse(result["found"])

    def test_falls_back_to_model_vision(self) -> None:
        description = _composite(
            local={"status": "ok", "ocr": {"status": "disabled"}},
            vision={"status": "ok", "ocr_text": "Conversas", "elements": [_element("Enviar")]},
        )
        tools = self._tools(description)
        self.assertTrue(tools.screen_contains_text("conversas")["found"])
        self.assertTrue(tools.screen_contains_text("enviar")["found"])

    def test_raises_without_any_text_source(self) -> None:
        description = _composite(local={"status": "ok", "ocr": {"status": "disabled"}}, vision={"status": "unavailable"})
        with self.assertRaises(RuntimeError):
            self._tools(description).screen_contains_text("x")


class _SequencePerception:
    def __init__(self, images: list[str]) -> None:
        self.images = images
        self.described = 0

    def screenshot(self) -> ScreenCapture:
        image = self.images.pop(0) if len(self.images) > 1 else self.images[0]
        return ScreenCapture(image=image, width=10, height=10)

    def describe(self, capture: ScreenCapture) -> dict[str, Any]:
        self.described += 1
        return {"visual_analysis": {"status": "ok"}}


class VerificationTests(unittest.TestCase):
    def test_polls_until_change_without_describing(self) -> None:
        perception = _SequencePerception(["a", "a", "a", "b"])
        verification = Verification(perception, poll_interval=0)
        before = verification.fingerprint()
        result = verification.verify_change(before)
        self.assertTrue(result.changed)
        self.assertEqual(perception.described, 0)

    def test_accepts_full_snapshot_as_before(self) -> None:
        perception = _SequencePerception(["a"])
        verification = Verification(perception, poll_attempts=3, poll_interval=0)
        result = verification.verify_change(verification.snapshot())
        self.assertEqual(result.status, VerificationStatus.NOT_CHANGED)

    def test_click_text_without_change_does_not_raise(self) -> None:
        class Controller:
            clicks: list[tuple[int, int]] = []

            def click(self, x: int, y: int, *, button: str = "left") -> None:
                self.clicks.append((x, y))

        class Fixed(Verification):
            def snapshot(self) -> Observation:
                vision = {"status": "ok", "elements": [_element("OK")]}
                return Observation(10, 10, observe_key, description=_composite(vision=vision))

        observe_key = Verification(_SequencePerception(["a"])).fingerprint().fingerprint
        controller = Controller()
        actions = VerifiedScreenActions(controller, Fixed(_SequencePerception(["a"]), poll_attempts=2, poll_interval=0))  # type: ignore[arg-type]
        result = actions.click_text("ok")
        self.assertTrue(result["clicked"])
        self.assertEqual(result["verification"]["status"], "not_changed")
        self.assertEqual(controller.clicks, [(5, 5)])

    def test_composite_status_reflects_sources(self) -> None:
        class Failing:
            def analyze(self, capture: ScreenCapture) -> dict[str, Any]:
                return {"status": "failed"}

        class Working:
            def analyze(self, capture: ScreenCapture) -> dict[str, Any]:
                return {"status": "ok"}

        capture = ScreenCapture(image="x", width=1, height=1)
        self.assertEqual(CompositeScreenAnalyzer(Failing()).analyze(capture)["status"], "failed")
        self.assertEqual(CompositeScreenAnalyzer(Failing(), Working()).analyze(capture)["status"], "ok")


class _FakeImage:
    def __init__(self, size: tuple[int, int]) -> None:
        self.size = size

    def resize(self, size: tuple[int, int]) -> _FakeImage:
        return _FakeImage(size)


class _ScriptedVision(VisionAdapter):
    def __init__(self, text: str) -> None:
        self.text = text
        self.sizes: list[tuple[int, int]] = []

    def analyze(self, image: Any, prompt: str, **kwargs: Any) -> VisionResponse:
        self.sizes.append(image.size)
        return VisionResponse(text=self.text)


class ModelVisionTests(unittest.TestCase):
    def test_downscales_and_rescales_coordinates(self) -> None:
        adapter = _ScriptedVision(
            '{"elements": ['
            '{"text": "OK", "x": 100, "y": 50, "width": 20, "height": 10, "confidence": 0.9},'
            '{"text": "Fora", "x": 5000, "y": 50, "width": 20, "height": 10, "confidence": 0.9}'
            "]}"
        )
        capture = ScreenCapture(image=_FakeImage((2560, 1440)), width=2560, height=1440)
        result = ModelVisionAnalyzer(adapter).analyze(capture)
        self.assertEqual(adapter.sizes, [(1280, 720)])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["elements"], [
            {"type": "other", "text": "OK", "x": 200, "y": 100, "width": 40, "height": 20, "confidence": 0.9}
        ])

    def test_unavailable_adapter_is_reported(self) -> None:
        capture = ScreenCapture(image=_FakeImage((100, 100)), width=100, height=100)
        result = ModelVisionAnalyzer(NullVisionAdapter()).analyze(capture)
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("reason", result)


class KeyTests(unittest.TestCase):
    def test_extended_and_new_aliases(self) -> None:
        self.assertEqual(_virtual_key("PageDown"), KeySpec(0x22, extended=True))
        self.assertEqual(_virtual_key("left"), KeySpec(0x25, extended=True))
        self.assertEqual(_virtual_key("f13"), KeySpec(0x7C))
        self.assertEqual(_virtual_key("a"), KeySpec(ord("A")))

    def test_punctuation_uses_layout_modifiers(self) -> None:
        self.assertEqual(_virtual_key("?", lambda char: 0x01BF), KeySpec(0xBF, (0x10,)))
        with self.assertRaises(ValueError):
            _virtual_key("?")


class SystemToolsTests(TempDirTestCase):
    def test_sensitive_environment_is_redacted_by_name(self) -> None:
        os.environ["DUQUE_TEST_API_KEY"] = "segredo"
        try:
            result = SystemTools().environment("DUQUE_TEST_API_KEY")
        finally:
            del os.environ["DUQUE_TEST_API_KEY"]
        self.assertIsNone(result["value"])
        self.assertTrue(result["redacted"])

    def test_read_any_file_truncates(self) -> None:
        target = self.tmp / "grande.txt"
        target.write_text("x" * 100, encoding="utf-8")
        result = SystemTools().read_any_file(str(target), max_bytes=10)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["bytes"], 10)

    def test_copy_into_itself_is_refused(self) -> None:
        source = self.tmp / "pasta"
        source.mkdir()
        with self.assertRaises(ValueError):
            SystemTools().copy_path(str(source), str(source / "copia"))

    def test_cannot_kill_itself(self) -> None:
        with self.assertRaises(PermissionError):
            SystemTools().kill_process(os.getpid())

    @unittest.skipIf(os.name == "nt", "usa /bin/sh")
    def test_run_command_timeout_does_not_hang(self) -> None:
        result = SystemTools().run_command("sleep 30", timeout=1)
        self.assertTrue(result["timed_out"])
        self.assertFalse(result["success"])


class CodeToolsSafetyTests(TempDirTestCase):
    def test_git_push_rejects_option_injection(self) -> None:
        tools = CodeTools(Workspace(self.tmp / "ws"))
        with self.assertRaises(ValueError):
            tools.git_push("--upload-pack=x")
        with self.assertRaises(ValueError):
            tools.git_push("origin", "-f")

    def test_run_tests_without_tests_dir_compiles(self) -> None:
        workspace = Workspace(self.tmp / "ws")
        workspace.write("ok.py", "x = 1\n")
        result = CodeTools(workspace).run_tests()
        self.assertTrue(result["success"])
        self.assertEqual(result["runner"], "compileall")


if __name__ == "__main__":
    unittest.main()
