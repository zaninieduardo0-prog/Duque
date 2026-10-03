"""Ajustes 10: Forja sem CMD e transparente, YouTube numa página, voz pelo nome, WhatsApp por perfil e operador."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from brain.autonomous_loop import AutonomousLoop
from brain.agent_state import AgentContext
from brain.model import ModelResponse
from brain.operator import looks_like_action
from brain.tool_schema import ToolSchemaRegistry, ToolSpec
from computer.assistant_tools import AssistantTools
from computer.chrome import match_profile
from computer.screen_pointer import ScreenPointer, parse_point
from computer.whatsapp_flow import WhatsAppDesktop, parse_many, parse_request
from core.executor import Executor
from core.windows import console_python
from forge.service import ForgeService, describe_action
from tests.helpers import TempDirTestCase
from voice.gate import ListenGate
from voice.local_wake import classify, decide


class ConsolePythonTests(unittest.TestCase):
    def test_pythonw_becomes_python(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pythonw, python = Path(tmp) / "pythonw.exe", Path(tmp) / "python.exe"
            pythonw.write_text("")
            self.assertEqual(console_python(str(pythonw)), str(pythonw))  # sem python.exe ao lado
            python.write_text("")
            self.assertEqual(console_python(str(pythonw)), str(python))
            self.assertEqual(console_python(str(python)), str(python))


class ForgeTransparencyTests(unittest.TestCase):
    def service(self) -> ForgeService:
        class Developer:
            event_sink: Any = None

        class FakeForge:
            progress: Any = None
            developer = Developer()

        service = ForgeService(FakeForge())  # type: ignore[arg-type]
        service._current = {"id": "1", "goal": "adicionar o Notion", "step": "iniciando", "started_at": 0}
        return service

    def test_agent_actions_are_recorded(self) -> None:
        from core.events import EventType

        service = self.service()
        self.assertIsNotNone(service.forge.developer.event_sink)  # type: ignore[attr-defined]
        service._on_agent_event(EventType.TASK_STARTED, tool="read_file", arguments={"path": "computer/apps.py"})
        service._on_agent_event(EventType.TASK_STARTED, tool="edit_file", arguments={"path": "computer/apps.py"})
        current = service.status()["current"]
        self.assertEqual(current["now"], "editando computer/apps.py")
        self.assertEqual(current["actions"], 2)
        self.assertEqual(current["activity"], ["lendo computer/apps.py", "editando computer/apps.py"])

    def test_waiting_is_explained(self) -> None:
        service = self.service()
        service._on_progress(None, "aguardando CI no GitHub")  # type: ignore[arg-type]
        self.assertIn("CI do GitHub", service.status()["current"]["waiting"])
        service._on_progress(None, "enviando branch x")  # type: ignore[arg-type]
        self.assertNotIn("waiting", service.status()["current"])

    def test_describe_action(self) -> None:
        self.assertEqual(describe_action("search_code", {"pattern": "notion"}), "procurando 'notion' no código")
        self.assertEqual(describe_action("run_checks", {}), "rodando compilação, testes e lint")


class ForgeStatusAgentTests(TempDirTestCase):
    def test_what_are_you_doing(self) -> None:
        import os
        from unittest import mock

        from brain.agent_loop import AgentLoop
        from brain.model import NullModel
        from computer.workspace import Workspace
        from memory.memory import Memory

        class Busy:
            def status(self) -> dict[str, Any]:
                return {"current": {"goal": "adicionar o Notion", "step": "rodada 1: agente programando", "started_at": 0,
                                    "now": "editando computer/apps.py", "activity": ["lendo computer/apps.py", "editando computer/apps.py"],
                                    "actions": 7}, "queued": 0, "history": []}

            def submit(self, goal: str) -> dict[str, Any]:
                return {"id": "x", "position": 1}

        with mock.patch.dict(os.environ, {"DUQUE_FORGE": "0"}):
            agent = AgentLoop(tasks=self.tasks, workspace=Workspace(self.tmp / "ws"), model=NullModel(),
                              memory=Memory(self.database), forge_service=Busy())
        self.addCleanup(agent.scheduled_runner.stop)
        text = agent.handle("o que você está fazendo agora?").text
        self.assertIn("Neste momento: editando computer/apps.py", text)
        self.assertIn("Antes disso: lendo computer/apps.py", text)
        self.assertIn("7 ações", text)


class YouTubeOnePageTests(unittest.TestCase):
    def test_reuses_open_youtube_window(self) -> None:
        opened: list[str] = []
        navigated: list[tuple[str, str]] = []
        tools = AssistantTools(
            fetch_text=lambda _u: '"videoId":"abcdefghijk"', open_target=opened.append,
            wait_window=lambda _f, _t: True, reuse_window=lambda f, u: navigated.append((f, u)) or True,
        )
        result = tools.youtube_play("charlie brown jr")
        self.assertTrue(result["playing"])
        self.assertEqual(opened, [])  # nenhuma página nova
        self.assertEqual(navigated, [("YouTube", "https://www.youtube.com/watch?v=abcdefghijk&autoplay=1")])

    def test_opens_when_no_youtube_window(self) -> None:
        opened: list[str] = []
        tools = AssistantTools(
            fetch_text=lambda _u: '"videoId":"abcdefghijk"', open_target=opened.append,
            wait_window=lambda _f, _t: True, reuse_window=lambda _f, _u: False,
        )
        tools.youtube_play("lofi")
        self.assertEqual(len(opened), 1)


class VoiceFlowTests(unittest.TestCase):
    def test_name_alone_opens_listening(self) -> None:
        gate = ListenGate()
        self.assertEqual(gate.decide("Telex.").action, "listen")
        self.assertTrue(gate.is_open)
        self.assertEqual(gate.decide("que horas são?").action, "respond")
        self.assertFalse(gate.is_open)  # respondeu: standby de novo
        self.assertEqual(gate.decide("e amanhã?").action, "ignore")

    def test_name_and_request_together(self) -> None:
        self.assertEqual(ListenGate().decide("Telex, que horas são?").action, "respond")

    def test_interrupt_while_speaking(self) -> None:
        gate = ListenGate()
        self.assertEqual(gate.decide("Telex", speaking=True).action, "stop")
        self.assertTrue(gate.is_open)

    def test_local_wake_call(self) -> None:
        self.assertEqual(decide(classify("telex"), False, False), ("call", None))
        self.assertEqual(decide(classify("telex que horas são"), False, False), ("call", None))
        self.assertEqual(decide(classify("boa tarde telex"), False, False), ("wake", "Boa tarde, TELEX."))
        self.assertEqual(decide(classify("telex"), False, True), ("none", None))  # em pausa

    @unittest.skipUnless(importlib.util.find_spec("numpy") is not None and importlib.util.find_spec("sounddevice") is not None
                         and importlib.util.find_spec("agents") is not None and importlib.util.find_spec("openwakeword") is not None,
                         "runtime de voz exige os pacotes de áudio")
    def test_preroll_resample(self) -> None:
        import duque_wake_v2 as runtime

        audio = (b"\x10\x00" * 16000)  # 1 s a 16 kHz
        self.assertEqual(len(runtime.resample_16k_to_24k(audio)), 24000 * 2)


class ChromeProfileTests(unittest.TestCase):
    PROFILES = [
        {"dir": "Default", "name": "Pessoal", "email": "du@gmail.com", "account": "Du"},
        {"dir": "Profile 2", "name": "Embralan", "email": "eduardo@embralan.com.br", "account": "Eduardo"},
    ]

    def test_match(self) -> None:
        self.assertEqual(match_profile("Embralan", self.PROFILES)["dir"], "Profile 2")  # type: ignore[index]
        self.assertEqual(match_profile("perfil pessoal", self.PROFILES)["dir"], "Default")  # type: ignore[index]
        self.assertEqual(match_profile("embralan.com.br", self.PROFILES)["dir"], "Profile 2")  # type: ignore[index]
        self.assertIsNone(match_profile("Faculdade", self.PROFILES))


class WhatsAppProfileParseTests(unittest.TestCase):
    def test_profile_in_request(self) -> None:
        request = parse_request("no perfil Embralan, mande uma mensagem para o Otávio dizendo que chego às 9h")
        assert request is not None
        self.assertEqual((request.contact, request.text, request.profile), ("Otávio", "chego às 9h", "Embralan"))

    def test_two_profiles_same_text(self) -> None:
        jobs = parse_many(
            "Quero que no perfil Pessoal você mande uma mensagem pelo WhatsApp Web para a Ana. "
            "E em seguida, no perfil Embralan, mande uma mensagem para o cliente Carlos. Ambos falando: reunião confirmada"
        )
        self.assertEqual([(j.profile, j.contact, j.hint, j.text) for j in jobs], [
            ("Pessoal", "Ana", "", "reunião confirmada"),
            ("Embralan", "Carlos", "cliente", "reunião confirmada"),
        ])


class FakeKeys:
    def __init__(self) -> None:
        self.log: list[str] = []

    def press(self, key: str) -> None:
        self.log.append(f"press:{key}")

    def hotkey(self, *keys: str) -> None:
        self.log.append("hotkey:" + "+".join(keys))

    def type_text(self, text: str) -> None:
        self.log.append(f"type:{text}")


class WhatsAppWebTests(unittest.TestCase):
    def flow(self, answers: list[str]) -> tuple[WhatsAppDesktop, FakeKeys, list[tuple[str, str]]]:
        keys, opened = FakeKeys(), []
        replies = iter(answers)
        flow = WhatsAppDesktop(
            open_app=lambda _n: None, open_target=lambda _u: None, keys=keys,
            ask_screen=lambda _q: next(replies), sleep=lambda _s: None,
            find_profile=lambda name: {"dir": "Profile 2", "name": "Embralan"} if "embralan" in name.casefold() else None,
            open_in_profile=lambda d, u: opened.append((d, u)),
            profile_names=lambda: ["Pessoal", "Embralan"],
        )
        return flow, keys, opened

    def test_sends_in_profile(self) -> None:
        flow, keys, opened = self.flow(["PRONTO", "Otávio", "sim"])
        result = flow.whatsapp_send("Otávio", "oi", profile="Embralan")
        self.assertTrue(result["sent"])
        self.assertIn("perfil Embralan", result["message"])
        self.assertEqual(opened, [("Profile 2", "https://web.whatsapp.com/")])
        self.assertIn("hotkey:ctrl+alt+/", keys.log)

    def test_already_open_goes_to_existing_tab(self) -> None:
        flow, keys, _ = self.flow(["DUPLICADO", "PRONTO", "Otávio", "sim"])
        flow.whatsapp_send("Otávio", "oi", profile="Embralan")
        self.assertLess(keys.log.index("hotkey:ctrl+w"), keys.log.index("hotkey:ctrl+shift+a"))

    def test_qr_code_and_unknown_profile(self) -> None:
        flow, _, _ = self.flow(["QRCODE"])
        self.assertIn("QR code", flow.whatsapp_send("Otávio", "oi", profile="Embralan")["error"])
        flow, _, _ = self.flow([])
        self.assertIn("Perfis: Pessoal, Embralan", flow.whatsapp_send("Otávio", "oi", profile="Faculdade")["error"])


class PointerTests(unittest.TestCase):
    def test_parse_point(self) -> None:
        self.assertEqual(parse_point('{"found": true, "x": 0.5, "y": 0.25}'), (0.5, 0.25))
        self.assertEqual(parse_point('ok {"found": true, "x": 50, "y": 25}'), (0.5, 0.25))
        self.assertIsNone(parse_point('{"found": false, "why": "não está"}'))
        self.assertIsNone(parse_point("nada"))

    @unittest.skipUnless(importlib.util.find_spec("PIL") is not None, "precisa do Pillow")
    def test_two_pass_locate_and_click(self) -> None:
        from PIL import Image

        answers = iter(['{"found": true, "x": 0.5, "y": 0.5}', '{"found": true, "x": 0.25, "y": 0.75}'])
        clicks: list[tuple[int, int]] = []
        pointer = ScreenPointer(lambda: Image.new("RGB", (2000, 1000)), lambda _i, _p: next(answers), lambda x, y: clicks.append((x, y)))
        result = pointer.click_on("botão Enviar")
        # 1ª passada: (1000, 500); recorte 700..1300 x 350..650; 2ª: 25%/75% do recorte.
        self.assertEqual(clicks, [(850, 575)])
        self.assertIn("Cliquei", result["message"])


class ScriptedModel:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)

    def respond(self, messages: list[dict[str, str]], **_: Any) -> ModelResponse:
        return ModelResponse(text=self.replies.pop(0))


class OperatorLoopTests(TempDirTestCase):
    def loop(self, replies: list[str], **kwargs: Any) -> tuple[AutonomousLoop, Executor]:
        from core.tasks import TaskManager

        executor = Executor(TaskManager(self.database))
        schemas = ToolSchemaRegistry()
        executor.register("current_time", lambda: {"message": "15:00"})
        schemas.register(ToolSpec("current_time", "hora"))
        return AutonomousLoop(ScriptedModel(replies), executor, schemas, **kwargs), executor  # type: ignore[arg-type]

    def test_cannot_is_honest(self) -> None:
        loop, executor = self.loop([json.dumps({"action": "cannot", "message": "Precisa da senha do banco, que eu não tenho."})])
        task = executor.tasks.create("pague o boleto")
        result = loop.run(AgentContext(goal="pague o boleto", task_id=task.id))
        self.assertFalse(result.success)
        self.assertIn("senha do banco", result.message)

    def test_time_limit(self) -> None:
        loop, executor = self.loop([json.dumps({"action": "tool", "tool": "current_time", "arguments": {}})] * 5, time_limit=-1)
        task = executor.tasks.create("x")
        result = loop.run(AgentContext(goal="x", task_id=task.id))
        self.assertIn("tempo limite", result.message)

    def test_looks_like_action(self) -> None:
        for text in ("organize minha área de trabalho", "Telex, baixe o instalador do VLC", "pode desinstalar o Zoom"):
            self.assertTrue(looks_like_action(text), text)
        for text in ("que horas são?", "bom dia", "você pode me ajudar?", "o que é um buraco negro"):
            self.assertFalse(looks_like_action(text), text)


if __name__ == "__main__":
    unittest.main()
