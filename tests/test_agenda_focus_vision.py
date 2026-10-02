from __future__ import annotations

import os
import time
import unittest
from datetime import datetime
from typing import Any
from unittest import mock

from brain.agent_loop import AgentLoop
from brain.model import NullModel
from brain.router import Intent, IntentRouter
from brain.planner import Planner
from brain.vision import VisionResponse
from brain.when import describe_moment, parse_when
from computer.screen_vision import ScreenVision
from computer.workspace import Workspace
from memory.memory import Memory
from tests.helpers import TempDirTestCase

FRIDAY = datetime(2026, 10, 2, 18, 40)


class WhenTests(unittest.TestCase):
    def check(self, text: str, expected: str, rest: str) -> None:
        when = parse_when(text, FRIDAY)
        assert when is not None, text
        self.assertEqual(when.moment.strftime("%d/%m %H:%M"), expected, text)
        self.assertEqual(when.rest, rest, text)

    def test_phrases(self) -> None:
        self.check("ligar pro João amanhã às 9h", "03/10 09:00", "ligar pro João")
        self.check("pagar a conta sexta às 18:30", "09/10 18:30", "pagar a conta")
        self.check("reunião dia 5 ao meio-dia", "05/10 12:00", "reunião")
        self.check("tomar remédio hoje à noite às 8", "02/10 20:00", "tomar remédio")
        self.check("dentista 05/10 às 14h", "05/10 14:00", "dentista")
        self.check("academia às 7", "03/10 07:00", "academia")
        self.check("comprar pão às 19h30", "02/10 19:30", "comprar pão")
        self.check("segunda de manhã ligar pro banco", "05/10 09:00", "ligar pro banco")
        self.check("dia 1 às 10h", "01/11 10:00", "")
        self.check("depois de amanhã às 15h", "04/10 15:00", "")

    def test_invalid(self) -> None:
        self.assertIsNone(parse_when("nada de data aqui", FRIDAY))
        self.assertIsNone(parse_when("hoje às 25h", FRIDAY))
        self.assertIsNone(parse_when("dia 31/02", FRIDAY))

    def test_describe(self) -> None:
        self.assertEqual(describe_moment(datetime(2026, 10, 3, 9, 0), FRIDAY), "amanhã às 09:00")
        self.assertEqual(describe_moment(datetime(2026, 10, 2, 12, 0), FRIDAY), "hoje ao meio-dia")


class RoutingTests(unittest.TestCase):
    def plan(self, text: str):
        intent = IntentRouter().route(text).intent
        return intent, [(step.tool, step.arguments) for step in Planner().build(text, intent.value).steps]

    def test_routes(self) -> None:
        self.assertEqual(self.plan("me lembre de ligar pro João amanhã às 9h")[1][0][0], "reminder_at")
        self.assertEqual(self.plan("minha agenda"), (Intent.SHORTCUT, [("reminders_list", {})]))
        self.assertEqual(self.plan("cancela o lembrete 2"), (Intent.SHORTCUT, [("reminder_cancel", {"index": 2})]))
        self.assertEqual(self.plan("foco por 50 minutos"), (Intent.SHORTCUT, [("focus_mode", {"action": "start", "minutes": 50.0})]))
        self.assertEqual(self.plan("foco por 30 minutos para estudar")[1][0][1]["action"], "start")
        self.assertEqual(self.plan("sair do modo foco"), (Intent.SHORTCUT, [("focus_mode", {"action": "stop"})]))
        self.assertEqual(self.plan("o que tem na minha tela?")[1][0][0], "describe_screen")


class AgentLifeTests(TempDirTestCase):
    def make_agent(self) -> AgentLoop:
        with mock.patch.dict(os.environ, {"DUQUE_FORGE": "0"}):
            agent = AgentLoop(tasks=self.tasks, workspace=Workspace(self.tmp / "ws"), model=NullModel(), memory=Memory(self.database))
        self.addCleanup(agent.scheduled_runner.stop)
        self.addCleanup(lambda: agent.focus_mode("stop"))
        return agent

    def test_reminder_lifecycle(self) -> None:
        agent = self.make_agent()
        result = agent.handle("me lembre de ligar pro João amanhã às 9h")
        self.assertIn("eu te lembro de ligar pro João", result.text)
        listing = agent.reminders_list()
        self.assertEqual([item["text"] for item in listing["reminders"]], ["ligar pro João"])
        self.assertIn("Cancelei", agent.handle("cancela os lembretes").text)
        self.assertEqual(agent.reminders_list()["reminders"], [])

    def test_reminder_survives_restart_and_fires(self) -> None:
        agent = self.make_agent()
        job = agent.scheduler.add("tomar remédio", time.time() + 3600, kind="reminder", agenda=True)
        agent.scheduled_runner.stop()
        with mock.patch.dict(os.environ, {"DUQUE_FORGE": "0"}):
            again = AgentLoop(tasks=self.tasks, workspace=Workspace(self.tmp / "ws"), model=NullModel(), memory=Memory(self.database))
        self.addCleanup(again.scheduled_runner.stop)
        self.assertEqual([item["text"] for item in again.reminders_list()["reminders"]], ["tomar remédio"])
        restored = next(item for item in again.scheduler.list() if item.id == job.id)
        restored.run_at = time.time() - 600  # simula horário que passou com o Duque desligado
        again.scheduler.run_due()
        turn = again.conversation.recent(1)[0]
        self.assertIn("lembrete: tomar remédio", turn.text)
        self.assertIn("estava desligado", turn.text)
        self.assertEqual(turn.channel, "aviso")

    def test_reminder_errors(self) -> None:
        agent = self.make_agent()
        self.assertFalse(agent.reminder_at("qualquer dia")["success"])
        self.assertFalse(agent.reminder_cancel(9)["success"])

    def test_focus_mode_pauses_music_and_silences(self) -> None:
        agent = self.make_agent()
        pressed: list[str] = []
        agent.now_playing.get = lambda: {"playing": True}  # type: ignore[method-assign]
        agent.assistant_tools.media = lambda action: pressed.append(action) or {"message": "ok"}  # type: ignore[method-assign]
        result = agent.focus_mode("start", 25)
        self.assertIn("Pausei a música", result["message"])
        self.assertEqual(pressed, ["play_pause"])
        agent.announce("timer qualquer")
        self.assertEqual(agent.conversation.recent(1)[0].channel, "silencioso")
        agent.announce("lembrete importante", urgent=True)
        self.assertEqual(agent.conversation.recent(1)[0].channel, "aviso")
        self.assertIn("encerrado", agent.focus_mode("stop")["message"])
        agent.announce("normal")
        self.assertEqual(agent.conversation.recent(1)[0].channel, "aviso")

    def test_focus_does_not_start_music(self) -> None:
        agent = self.make_agent()
        pressed: list[str] = []
        agent.now_playing.get = lambda: {"playing": False}  # type: ignore[method-assign]
        agent.assistant_tools.media = lambda action: pressed.append(action) or {}  # type: ignore[method-assign]
        agent.focus_mode("start", 10)
        self.assertEqual(pressed, [])
        self.assertFalse(agent.focus_mode("start", 0).get("success", True))


class FakeImage:
    def __init__(self) -> None:
        self.size = (3840, 2160)

    def copy(self) -> FakeImage:
        return self

    def thumbnail(self, limit: tuple[int, int]) -> None:
        self.size = (1600, 900)


class FakeAdapter:
    def __init__(self, text: str = "Há um erro de importação no VS Code.") -> None:
        self.text = text
        self.prompts: list[str] = []

    def analyze(self, image: Any, prompt: str, **kwargs: Any) -> VisionResponse:
        self.prompts.append(prompt)
        return VisionResponse(text=self.text)


class ScreenVisionTests(unittest.TestCase):
    def test_describes_with_question(self) -> None:
        image, adapter = FakeImage(), FakeAdapter()
        result = ScreenVision(lambda: image, adapter).describe_screen("que erro é esse?")
        self.assertEqual(result["message"], "Há um erro de importação no VS Code.")
        self.assertIn("que erro é esse?", adapter.prompts[0])
        self.assertEqual(image.size, (1600, 900))

    def test_failures_are_reported(self) -> None:
        def no_screen() -> Any:
            raise RuntimeError("sem tela")

        self.assertFalse(ScreenVision(no_screen, FakeAdapter()).describe_screen()["success"])
        self.assertFalse(ScreenVision(FakeImage, FakeAdapter("")).describe_screen()["success"])


if __name__ == "__main__":
    unittest.main()
