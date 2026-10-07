"""Pente fino do cérebro: roteamento, confirmações, autocorreção e laço autônomo.

Cada teste trava um bug encontrado na revisão (ações duplicadas, janelas a mais,
"sim" valendo para tudo, pedidos negados executados...).
"""

from __future__ import annotations

import json
import os
import time
import unittest
from datetime import datetime
from typing import Any
from unittest import mock

from brain.agent_loop import AgentLoop
from brain.agent_state import AgentContext
from brain.autonomous_loop import AutonomousLoop
from brain.compound import collapse_browser, plan_steps
from brain.model import ModelResponse, NullModel, OpenAIResponsesModel, extract_json_object
from brain.operator import looks_like_action
from brain.planner import Planner
from brain.router import Intent, IntentRouter
from brain.self_correction import SelfCorrection
from brain.tool_schema import ToolSchemaRegistry, ToolSpec
from brain.when import parse_when
from computer.workspace import Workspace
from core.executor import Executor
from core.task_engine import TaskEngine
from memory.memory import Memory
from tests.helpers import ScriptedModel, TempDirTestCase


def tool(tool_name: str, /, **arguments: Any) -> str:
    return json.dumps({"action": "tool", "tool": tool_name, "arguments": arguments})


def finish(message: str) -> str:
    return json.dumps({"action": "finish", "message": message})


class SchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schemas = ToolSchemaRegistry()
        self.schemas.register(ToolSpec("kill_process", "", ("pid",), {"pid": int, "force": bool}))
        self.schemas.register(ToolSpec("wait", "", ("seconds",), {"seconds": (int, float)}))

    def test_bool_is_not_a_number(self) -> None:
        self.assertFalse(self.schemas.validate("kill_process", {"pid": True}).valid)
        self.assertFalse(self.schemas.validate("wait", {"seconds": False}).valid)
        self.assertTrue(self.schemas.validate("kill_process", {"pid": 10, "force": True}).valid)

    def test_integral_float_becomes_int(self) -> None:
        arguments: dict[str, Any] = {"pid": 3.0}
        self.assertTrue(self.schemas.validate("kill_process", arguments).valid)
        self.assertEqual(arguments["pid"], 3)
        self.assertIsInstance(arguments["pid"], int)
        self.assertFalse(self.schemas.validate("kill_process", {"pid": 3.5}).valid)


class RouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = IntentRouter()

    def intent(self, text: str, context_app: str | None = None) -> Intent:
        return self.router.route(text, context_app).intent

    def test_negated_requests_never_act(self) -> None:
        for text in ("não abra o chrome", "nao feche o spotify", "não quero que abra o whatsapp", "não pesquise nada", "Telex, não apague o arquivo a.txt"):
            with self.subTest(text=text):
                self.assertEqual(self.intent(text), Intent.CHAT)

    def test_how_to_questions_are_chat(self) -> None:
        for text in ("como faço para abrir o chrome?", "como abrir o bloco de notas", "por que o chrome está aberto?", "você sabe programar?"):
            with self.subTest(text=text):
                self.assertEqual(self.intent(text), Intent.CHAT)
        self.assertEqual(self.intent("como está o clima?"), Intent.WEATHER)

    def test_polite_requests_still_act(self) -> None:
        self.assertEqual(self.intent("pode abrir o spotify?"), Intent.OPEN_APP)
        self.assertEqual(self.intent("Telex, você consegue fechar o chrome?"), Intent.CLOSE_APP)

    def test_loose_words_do_not_trigger_tools(self) -> None:
        for text in ("qual a pasta de downloads?", "tenho um arquivo importante amanhã", "o google é bom?", "me fala do programa do jô", "debug"):
            with self.subTest(text=text):
                self.assertEqual(self.intent(text), Intent.CHAT)

    def test_volume_and_power_variants(self) -> None:
        planner = Planner()
        for text, direction in (("aumenta o volume", "up"), ("sobe o volume", "up"), ("abaixa o volume", "down"), ("baixa o som", "down")):
            with self.subTest(text=text):
                self.assertEqual(self.intent(text), Intent.SYSTEM)
                steps = planner.build(text, "system").steps
                self.assertEqual((steps[0].tool, steps[0].arguments), ("volume", {"direction": direction}))
        self.assertEqual(self.intent("desliga o computador"), Intent.SYSTEM)

    def test_context_app_only_for_pronoun_questions(self) -> None:
        self.assertEqual(self.intent("ele está aberto?", "spotify"), Intent.CHECK_APP)
        self.assertEqual(self.intent("o mercado está aberto?", "spotify"), Intent.CHAT)

    def test_close_pronoun_uses_last_app(self) -> None:
        self.assertEqual(self.intent("fecha ele", "spotify"), Intent.CLOSE_APP)
        step = Planner().build("fecha ele", "close_app", context_app="spotify").steps[0]
        self.assertEqual(step.arguments, {"name": "spotify"})

    def test_open_google_opens_the_page(self) -> None:
        step = Planner().build("abra o google", self.intent("abra o google").value).steps[0]
        self.assertEqual((step.tool, step.arguments), ("open_url", {"url": "https://www.google.com"}))

    def test_false_reminder_trigger(self) -> None:
        self.assertEqual(self.intent("não consigo lembrar o nome do filme"), Intent.CHAT)
        self.assertEqual(self.intent("me lembre de beber água"), Intent.REMINDER)


class CompoundTests(unittest.TestCase):
    def test_questions_are_not_split(self) -> None:
        text = "como faço para abrir o chrome e fechar o spotify?"
        self.assertEqual(plan_steps(text), [text])

    def test_list_of_apps_opens_each(self) -> None:
        self.assertEqual(plan_steps("abre o vscode e o spotify"), ["abra o vscode", "abra o spotify"])

    def test_browser_then_search_is_one_window(self) -> None:
        self.assertEqual(collapse_browser(plan_steps("abra o chrome e pesquise o dólar")), ["pesquise o dólar no google"])
        self.assertEqual(collapse_browser(plan_steps("abra o chrome e entre no youtube")), ["abra youtube"])
        self.assertEqual(
            collapse_browser(plan_steps("abra o chrome, pesquise o dólar e depois feche o chrome")),
            ["pesquise o dólar no google", "feche o chrome"],
        )


class OperatorTriggerTests(unittest.TestCase):
    def test_past_tense_and_idioms_are_not_requests(self) -> None:
        for text in ("abri o chrome e travou", "mandei mensagem ontem", "faz sentido", "salve", "liguei o pc"):
            with self.subTest(text=text):
                self.assertFalse(looks_like_action(text))
        self.assertTrue(looks_like_action("abra o paint e escreva TELEX"))


class SelfCorrectionTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.executor = Executor(self.tasks)
        self.calls: list[str] = []

        def make(name: str, fail_times: int = 0) -> Any:
            state = {"left": fail_times}

            def run(**_: Any) -> Any:
                self.calls.append(name)
                if state["left"] > 0:
                    state["left"] -= 1
                    raise RuntimeError(f"{name} falhou")
                return {"message": f"{name} ok"}

            return run

        self.executor.register("note_add", make("note_add"))
        self.executor.register("read_file", make("read_file", fail_times=1))
        self.executor.register("run_tests", lambda: {"success": False, "stdout": "1 failed"})
        self.correction = SelfCorrection(TaskEngine(self.executor))

    def test_successful_steps_are_not_repeated(self) -> None:
        report = self.correction.run(self.tasks.create("x"), lambda error, attempt: [("note_add", {"text": "a"}), ("read_file", {"path": "a"})])
        self.assertTrue(report.success)
        self.assertEqual(self.calls, ["note_add", "read_file", "read_file"])  # nota não duplicada

    def test_command_with_result_is_not_retried(self) -> None:
        seen: list[int] = []

        def factory(error: Any, attempt: int) -> Any:
            seen.append(attempt)
            return [("run_tests", {})]

        report = self.correction.run(self.tasks.create("x"), factory, max_attempts=3)
        self.assertFalse(report.success)
        self.assertEqual(seen, [1])

    def test_confirmation_only_covers_the_first_plan(self) -> None:
        self.executor.register("delete_file", lambda path: {"deleted": True, "path": path})
        self.executor.register("flaky", mock.Mock(side_effect=[RuntimeError("x"), {"ok": True}]))
        plans = [[("flaky", {})], [("delete_file", {"path": "a"})]]
        report = self.correction.run(self.tasks.create("x"), lambda error, attempt: plans[attempt - 1], max_attempts=2, confirmed=True)
        self.assertFalse(report.success)
        self.assertTrue(report.results[-1].result.confirmation_required)


class AutonomousTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.executor = Executor(self.tasks)
        self.schemas = ToolSchemaRegistry()
        self.opened: list[str] = []
        self.executor.register("open_app", lambda name: self.opened.append(name) or {"opened": True, "app": name})
        self.executor.register("delete_any_file", lambda path: {"deleted": True, "path": path})
        self.executor.register("current_time", lambda: {"message": "15:00"})
        self.executor.register("write_file", lambda path, content: {"created": True, "path": path})
        self.schemas.register(ToolSpec("open_app", "", ("name",), {"name": str}))
        self.schemas.register(ToolSpec("delete_any_file", "", ("path",), {"path": str}))
        self.schemas.register(ToolSpec("current_time", ""))
        self.schemas.register(ToolSpec("write_file", "", ("path", "content"), {"path": str, "content": str}))

    def run_loop(self, replies: list[str], **kwargs: Any) -> Any:
        loop = AutonomousLoop(ScriptedModel(replies), self.executor, self.schemas, sleep=lambda _s: None, **kwargs)
        task = self.tasks.create("x")
        return loop, task, loop.run(AgentContext(goal="x", task_id=task.id))

    def test_same_app_is_not_reopened(self) -> None:
        _, _, result = self.run_loop([tool("open_app", name="chrome"), tool("current_time"), tool("open_app", name="chrome"), finish("ok")])
        self.assertTrue(result.success)
        self.assertEqual(self.opened, ["chrome"])

    def test_resume_approves_only_the_blocked_action(self) -> None:
        loop, task, first = self.run_loop([tool("open_app", name="x"), tool("delete_any_file", path="a")])
        self.assertEqual(first.pending_action, ("delete_any_file", {"path": "a"}))
        loop.model = ScriptedModel([tool("delete_any_file", path="b"), finish("x")])
        resumed = loop.run(AgentContext(goal="x", task_id=task.id), approved_action=first.pending_action, resume_messages=first.messages)
        self.assertTrue(resumed.executions[0].success)  # "a" apagado com o sim
        self.assertTrue(resumed.executions[-1].confirmation_required)  # "b" pede de novo
        self.assertEqual(self.opened, ["x"])  # nada refeito

    def test_model_errors_are_bounded(self) -> None:
        model = mock.Mock()
        model.respond.side_effect = TimeoutError("sem rede")
        loop = AutonomousLoop(model, self.executor, self.schemas, sleep=lambda _s: None)
        task = self.tasks.create("x")
        result = loop.run(AgentContext(goal="x", task_id=task.id))
        self.assertFalse(result.success)
        self.assertEqual(model.respond.call_count, 3)

    def test_finish_without_evidence_is_bounded(self) -> None:
        _, _, result = self.run_loop([finish("pronto")] * 5)
        self.assertFalse(result.success)
        self.assertIn("comprovar", result.message)

    def test_alternating_loop_is_detected(self) -> None:
        _, _, result = self.run_loop([tool("current_time"), tool("open_app", name="y")] * 8)
        self.assertFalse(result.success)
        self.assertIn("Loop", result.error or "")

    def test_blocked_tools_are_rejected(self) -> None:
        _, _, result = self.run_loop([tool("write_file", path="brain/x.py", content="x"), tool("current_time"), finish("ok")], blocked_tools={"write_file"})
        self.assertTrue(result.success)
        self.assertEqual(len(result.executions), 1)

    def test_context_is_trimmed(self) -> None:
        loop = AutonomousLoop(mock.Mock(), self.executor, self.schemas)
        messages = [{"role": "user", "content": str(index)} for index in range(500)]
        self.assertLessEqual(len(loop._trim(messages)), 62)
        self.assertLess(len(loop._feedback("x", mock.Mock(success=True, value="z" * 100000, verification=None))), 7000)


class ModelTests(unittest.TestCase):
    def test_extract_json(self) -> None:
        self.assertEqual(extract_json_object('Claro! {"a": 1} pronto'), {"a": 1})
        self.assertEqual(extract_json_object('```json\n{"a": 2}\n```'), {"a": 2})
        self.assertIsNone(extract_json_object("nada"))

    def test_openai_client_is_reused_with_timeout(self) -> None:
        fake = mock.Mock()
        fake.OpenAI.return_value.responses.create.return_value = mock.Mock(output_text="oi")
        with mock.patch.dict("sys.modules", {"openai": fake}):
            model = OpenAIResponsesModel(api_key="k", timeout=12)
            model.respond([{"role": "user", "content": "a"}])
            model.respond([{"role": "user", "content": "b"}])
        self.assertEqual(fake.OpenAI.call_count, 1)
        self.assertEqual(fake.OpenAI.call_args.kwargs["timeout"], 12)


class WhenTests(unittest.TestCase):
    def test_relative_durations(self) -> None:
        now = datetime(2026, 10, 2, 15, 0)
        parsed = parse_when("daqui a 2 horas ligar pro banco", now)
        assert parsed is not None
        self.assertEqual(parsed.moment, datetime(2026, 10, 2, 17, 0))
        self.assertEqual(parsed.rest, "ligar pro banco")

    def test_same_weekday_without_hour_is_next_week(self) -> None:
        parsed = parse_when("sexta", datetime(2026, 10, 2, 15, 0))  # sexta à tarde
        assert parsed is not None
        self.assertEqual(parsed.moment, datetime(2026, 10, 9, 9, 0))


class AgentTests(TempDirTestCase):
    def make_agent(self, model: Any = None) -> AgentLoop:
        with mock.patch.dict(os.environ, {"DUQUE_FORGE": "0", "DUQUE_OPERATOR": "0"}):
            agent = AgentLoop(tasks=self.tasks, workspace=Workspace(self.tmp / "ws"), model=model or NullModel(), memory=Memory(self.database))
        self.addCleanup(agent.scheduled_runner.stop)
        self.volume: list[str] = []
        agent.executor.register("volume", lambda direction, steps=2: self.volume.append(direction) or {"message": "Volume ajustado."})
        (self.tmp / "ws").mkdir(exist_ok=True)
        (self.tmp / "ws" / "a.txt").write_text("x", encoding="utf-8")
        return agent

    def test_offline_chat_does_not_echo(self) -> None:
        result = self.make_agent().handle("me conta uma piada")
        self.assertNotEqual(result.text, "me conta uma piada")
        self.assertIn("sem o modelo", result.text)

    def test_confirmation_accepts_natural_yes_and_runs_remaining_steps(self) -> None:
        agent = self.make_agent()
        asked = agent.handle("apague o arquivo a.txt, depois aumente o volume")
        self.assertIn("Preciso da sua confirmação", asked.text)
        self.assertEqual(self.volume, [])
        self.assertFalse(agent._is_confirmation("pode não"))
        done = agent.handle("Telex, sim, pode apagar.")
        self.assertFalse((self.tmp / "ws" / "a.txt").exists())
        self.assertEqual(self.volume, ["up"])
        self.assertIn("Volume ajustado", done.text)
        self.assertIsNone(agent._pending_confirmation)

    def test_new_request_cancels_pending_instead_of_blocking(self) -> None:
        agent = self.make_agent()
        agent.handle("apague o arquivo a.txt")
        result = agent.handle("aumente o volume")
        self.assertIn("Cancelei", result.text)
        self.assertEqual(self.volume, ["up"])
        self.assertIsNone(agent._pending_confirmation)
        self.assertTrue((self.tmp / "ws" / "a.txt").exists())

    def test_pending_confirmation_expires(self) -> None:
        agent = self.make_agent()
        agent.handle("apague o arquivo a.txt")
        assert agent._pending_confirmation is not None
        agent._pending_confirmation.created_at = time.time() - 3600
        result = agent.handle("sim")
        self.assertIn("expirou", result.text)
        self.assertTrue((self.tmp / "ws" / "a.txt").exists())

    def test_resume_does_not_repeat_steps_that_already_ran(self) -> None:
        plan = {"goal": "x", "steps": [
            {"kind": "tool", "tool": "open_app", "arguments": {"name": "explorer"}},
            {"kind": "tool", "tool": "delete_file", "arguments": {"path": "a.txt"}},
        ]}
        agent = self.make_agent(ScriptedModel([json.dumps(plan)]))
        opened: list[str] = []
        agent.executor.register("open_app", lambda name: opened.append(name) or {"opened": True, "app": name})
        asked = agent.handle("faça a faxina")
        self.assertIn("delete_file", asked.text)
        agent.handle("sim")
        self.assertEqual(opened, ["explorer"])
        self.assertFalse((self.tmp / "ws" / "a.txt").exists())

    def test_schedule_task_limits(self) -> None:
        agent = self.make_agent()
        steps = [{"tool": "current_time", "arguments": {}}]
        with self.assertRaises(ValueError):
            agent._schedule_task("x", 10, steps, repeat_seconds=1)
        with self.assertRaises(ValueError):
            agent._schedule_task("x", 10, [{"tool": "delete_file", "arguments": {"path": "a.txt"}}])
        with self.assertRaises(ValueError):
            agent._schedule_task("x", True, steps)  # type: ignore[arg-type]
        self.assertIn("job_id", agent._schedule_task("x", 10, steps, repeat_seconds=120))

    def test_voice_duplicate_call_runs_once(self) -> None:
        agent = self.make_agent()
        agent.handle("aumente o volume", channel="voz", record=False)
        agent.handle("aumente o volume", channel="voz", record=False)
        self.assertEqual(self.volume, ["up"])

    def test_stale_last_app_is_forgotten(self) -> None:
        agent = self.make_agent()
        agent._last_app = "spotify"
        self.assertEqual(agent._last_app, "spotify")
        agent._last_app_at -= 3600
        self.assertIsNone(agent._last_app)

    def test_invalid_daily_summary_setting_does_not_crash(self) -> None:
        with mock.patch.dict(os.environ, {"DUQUE_DAILY_SUMMARY": "25:00"}):
            self.make_agent()

    def test_task_record_survives_unserializable_result(self) -> None:
        agent = self.make_agent()
        agent._remember_task("t", {"result": object(), "big": "x" * 10000})

    def test_routine_cannot_call_itself(self) -> None:
        agent = self.make_agent()
        saved = agent.routines.routine_save("ciclo", "modo ciclo")
        self.assertIs(saved.get("success"), False)

    def test_forge_questions_do_not_start_jobs(self) -> None:
        self.assertFalse(AgentLoop._forge_requested("o que é a forja?"))
        self.assertTrue(AgentLoop._forge_requested("coloque na forja: adicionar o Notion"))

    def test_greeting_with_telex_is_small_talk(self) -> None:
        self.assertTrue(AgentLoop._is_small_talk("Bom dia, Telex"))

    def test_chat_model_used_for_unmatched_reminder_words(self) -> None:
        model = ScriptedModel(["sem plano", "Foi Matrix, Du."])
        agent = self.make_agent(model)
        result = agent.handle("me ajuda a lembrar daquele filme com o Keanu")
        self.assertEqual(result.text, "Foi Matrix, Du.")


class ModelResponseSanity(unittest.TestCase):
    def test_null_model_still_echoes_for_tools(self) -> None:
        # O NullModel continua o dublê dos testes; quem não pode ecoar é a conversa.
        self.assertEqual(NullModel().respond([{"role": "user", "content": "x"}]), ModelResponse(text="x"))


if __name__ == "__main__":
    unittest.main()
