from __future__ import annotations

import threading
import unittest
from datetime import datetime

from brain.planner import Planner
from brain.router import Intent, IntentRouter
from computer.apps import find_app_in_text, resolve_app
from computer.assistant_tools import VK_VOLUME_UP, AssistantTools, describe_duration, format_number, safe_eval
from memory.memory import Memory
from tests.helpers import TempDirTestCase

FIXED = datetime(2026, 10, 2, 17, 5)


class SafeEvalTests(unittest.TestCase):
    def test_arithmetic(self) -> None:
        cases = {"2+2": 4, "2*(3+4)": 14, "10/4": 2.5, "2^10": 1024, "sqrt(81)": 9, "-3+1": -2, "1,5*2": 3, "pi*0": 0}
        for expression, expected in cases.items():
            with self.subTest(expression=expression):
                self.assertAlmostEqual(safe_eval(expression), expected)

    def test_rejects_code(self) -> None:
        for expression in ("__import__('os').system('x')", "open('a')", "a.b", "[1,2]", "lambda: 1", "2**100000"):
            with self.subTest(expression=expression), self.assertRaises((ValueError, SyntaxError)):
                safe_eval(expression)

    def test_formatting(self) -> None:
        self.assertEqual(format_number(1234567), "1.234.567")
        self.assertEqual(format_number(2.5), "2,5")
        self.assertEqual(describe_duration(5400), "1 hora e 30 minutos")
        self.assertEqual(describe_duration(1), "1 segundo")


class AssistantToolsTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.opened: list[str] = []
        self.keys: list[tuple[int, int]] = []
        self.notified: list[str] = []
        self.requests: list[str] = []

        def fetch(url: str):
            self.requests.append(url)
            if "geocoding" in url:
                return {"results": [{"name": "Piracicaba", "latitude": -22.7, "longitude": -47.6}]}
            return {
                "current": {"temperature_2m": 27.4, "apparent_temperature": 29.1, "weather_code": 2},
                "daily": {"temperature_2m_min": [18.2], "temperature_2m_max": [31.6], "precipitation_probability_max": [40]},
            }

        self.tools = AssistantTools(
            Memory(self.database),
            notify=self.notified.append,
            fetch_json=fetch,
            open_target=self.opened.append,
            press_key=lambda vk, times: self.keys.append((vk, times)),
            clock=lambda: FIXED,
        )

    def test_current_time(self) -> None:
        self.assertEqual(self.tools.current_time()["message"], "São 17:05 de sexta-feira, 2 de outubro de 2026.")

    def test_weather(self) -> None:
        result = self.tools.weather("Piracicaba")
        self.assertIn("27°C", result["message"])
        self.assertIn("parcialmente nublado", result["message"])
        self.assertIn("40% de chance de chuva", result["message"])
        self.assertIn("name=Piracicaba", self.requests[0])

    def test_weather_unknown_city(self) -> None:
        tools = AssistantTools(fetch_json=lambda url: {"results": []})
        self.assertFalse(tools.weather("Xyzzy")["success"])

    def test_calculate(self) -> None:
        self.assertEqual(self.tools.calculate("2*(3+4)")["message"], "2*(3+4) = 14")
        self.assertFalse(self.tools.calculate("1/0")["success"])
        self.assertFalse(self.tools.calculate("import os")["success"])

    def test_notes_round_trip(self) -> None:
        self.tools.note_add("comprar pão")
        self.tools.note_add("ligar para o banco")
        self.assertIn("2. ligar para o banco", self.tools.notes_list()["message"])
        self.tools.note_delete(1)
        self.assertEqual([note["text"] for note in self.tools.notes_list()["notes"]], ["ligar para o banco"])
        self.assertFalse(self.tools.note_delete(5)["success"])

    def test_timer_fires_notification(self) -> None:
        done = threading.Event()
        tools = AssistantTools(notify=lambda text: (self.notified.append(text), done.set()))
        result = tools.timer_set(1, "tirar o bolo")
        self.assertIn("1 segundo", result["message"])
        self.assertEqual(len(tools.timers_list()["timers"]), 1)
        self.assertTrue(done.wait(5))
        self.assertEqual(self.notified, ["Du, lembrete: tirar o bolo."])
        self.assertEqual(tools.timers_list()["timers"], [])

    def test_timer_cancel_and_limits(self) -> None:
        timer_id = self.tools.timer_set(600)["id"]
        self.assertTrue(self.tools.timer_cancel(timer_id)["cancelled"])
        self.assertFalse(self.tools.timer_set(0)["success"])
        self.assertFalse(self.tools.timer_cancel("nao-existe")["success"])

    def test_media_and_volume_keys(self) -> None:
        self.tools.media("next")
        self.tools.volume("up", 3)
        self.assertEqual(self.keys, [(0xB0, 1), (VK_VOLUME_UP, 3)])
        self.assertFalse(self.tools.media("dançar")["success"])
        self.assertFalse(self.tools.volume("lado")["success"])

    def test_shortcuts_open_targets(self) -> None:
        self.tools.youtube("lofi hip hop")
        self.tools.spotify("Daft Punk")
        self.tools.maps("Avenida Paulista")
        self.assertIn("search_query=lofi+hip+hop", self.opened[0])
        self.assertEqual(self.opened[1], "spotify:search:Daft%20Punk")
        self.assertIn("Avenida+Paulista", self.opened[2])

    def test_open_folder_and_find_files(self) -> None:
        folder = self.tmp / "projetos"
        (folder / "sub").mkdir(parents=True)
        (folder / "sub" / "Relatorio_Final.pdf").write_text("x", encoding="utf-8")
        self.assertTrue(self.tools.open_folder(str(folder))["path"].endswith("projetos"))
        self.assertFalse(self.tools.open_folder(str(self.tmp / "nao-existe"))["success"])
        found = self.tools.find_files("relatorio", str(folder))
        self.assertEqual(len(found["files"]), 1)

    def test_system_status_has_disk(self) -> None:
        status = self.tools.system_status()
        self.assertIn("disk_free_gb", status)
        self.assertTrue(status["message"].endswith("."))


class IntentAndPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = IntentRouter()
        self.planner = Planner()

    def plan(self, text: str):
        route = self.router.route(text)
        plan = self.planner.build(text, route.intent.value)
        return route.intent, [(step.tool, step.arguments) for step in plan.steps]

    def test_everyday_requests(self) -> None:
        self.assertEqual(self.plan("que horas são?"), (Intent.TIME, [("current_time", {})]))
        self.assertEqual(self.plan("como está o clima em São Paulo hoje?"), (Intent.WEATHER, [("weather", {"city": "são paulo"})]))
        self.assertEqual(self.plan("próxima música"), (Intent.MEDIA, [("media", {"action": "next"})]))
        self.assertEqual(self.plan("anote que preciso pagar a luz"), (Intent.NOTE, [("note_add", {"text": "preciso pagar a luz"})]))
        self.assertEqual(self.plan("quanto é 15*3?"), (Intent.CALC, [("calculate", {"expression": "15*3"})]))
        self.assertEqual(self.plan("aumente o volume"), (Intent.SYSTEM, [("volume", {"direction": "up"})]))

    def test_reminder_with_duration_becomes_timer(self) -> None:
        intent, steps = self.plan("me lembre de tirar o bolo em 1 hora e 30 minutos")
        self.assertEqual(intent, Intent.REMINDER)
        self.assertEqual(steps, [("timer_set", {"seconds": 5400.0, "label": "tirar o bolo"})])

    def test_any_known_app_can_be_opened_and_closed(self) -> None:
        self.assertEqual(self.plan("abre o spotify"), (Intent.OPEN_APP, [("open_app", {"name": "spotify"})]))
        self.assertEqual(self.plan("Duque, feche o discord"), (Intent.CLOSE_APP, [("close_app", {"name": "discord"})]))
        self.assertEqual(self.router.route("abra o arquivo relatorio word").intent, Intent.FILE_OPERATION)

    def test_folders_and_file_search(self) -> None:
        self.assertEqual(self.plan("abre a pasta downloads"), (Intent.FILE_OPERATION, [("open_folder", {"name": "downloads"})]))
        self.assertEqual(self.plan("procura arquivos chamados relatorio"), (Intent.FILE_OPERATION, [("find_files", {"name": "relatorio"})]))
        self.assertEqual(self.plan('encontre o arquivo "notas 2026"'), (Intent.FILE_OPERATION, [("find_files", {"name": "notas 2026"})]))
        self.assertEqual(self.plan("leia o arquivo notas.txt")[1], [("read_file", {"path": "notas.txt"})])

    def test_shortcuts(self) -> None:
        cases = {
            "toca lofi no youtube": [("youtube_play", {"query": "lofi"})],
            "coloca Daft Punk no spotify": [("spotify", {"query": "Daft Punk"})],
            "como chego na Avenida Paulista?": [("maps", {"destination": "Avenida Paulista"})],
            "como está o computador?": [("system_status", {})],
            'copia "teste do Duque" para a área de transferência': [("clipboard_write", {"text": "teste do Duque"})],
            "o que tem na área de transferência?": [("clipboard_read", {})],
            "bloqueia a tela": [("lock_screen", {})],
            "meus timers": [("timers_list", {})],
            "cancela os timers": [("timer_cancel", {})],
        }
        for text, steps in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.plan(text), (Intent.SHORTCUT, steps))
        self.assertEqual(self.plan("abre o youtube")[0], Intent.OPEN_APP)

    def test_find_app_in_text(self) -> None:
        self.assertEqual(find_app_in_text("abre o visual studio code"), "visual studio code")
        self.assertIsNone(find_app_in_text("abre a geladeira"))
        self.assertIsNotNone(resolve_app("Spotify"))


if __name__ == "__main__":
    unittest.main()
