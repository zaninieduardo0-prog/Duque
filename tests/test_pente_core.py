"""Pente fino do núcleo: regressões de ações duplicadas, abas a mais e estado preso."""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from automation.runner import MISSED_TASK_GRACE, ScheduledTaskRunner
from automation.scheduler import MIN_REPEAT_SECONDS, Scheduler
from core.events import Event, EventBus, EventType
from core.executor import Executor
from core.hud import abrir_hud
from core import hud as hud_module
from core.instance import InstanceLock
from core.security import RiskLevel, SecurityPolicy
from core.task_engine import TaskEngine
from core.tasks import CONFIRMATION_TTL, TaskManager, TaskStatus
from memory.database import MemoryDatabase
from memory.memory import Memory, MemoryLayer
from tests.helpers import TempDirTestCase

ROOT = Path(__file__).resolve().parents[1]


class EventBusTests(unittest.TestCase):
    def test_broken_subscriber_does_not_break_emitter_or_others(self) -> None:
        bus = EventBus()
        seen: list[EventType] = []

        def broken(event: Event) -> None:
            raise ValueError("HUD quebrado")

        bus.subscribe(None, broken)
        bus.subscribe(EventType.TASK_STARTED, lambda event: seen.append(event.type))
        with self.assertLogs("core.events", level="ERROR"):
            bus.emit(Event(EventType.TASK_STARTED))
        self.assertEqual(seen, [EventType.TASK_STARTED])


class _BrokenVerification:
    def snapshot(self) -> Any:
        return object()

    def verify_change(self, before: Any) -> Any:
        raise RuntimeError("sem tela")


class ExecutorTests(TempDirTestCase):
    def test_verification_failure_does_not_leave_task_running(self) -> None:
        executor = Executor(self.tasks, verification=_BrokenVerification())
        clicks: list[int] = []
        executor.register("ui_click", lambda: clicks.append(1) or {"ok": True})
        task = self.tasks.create("clicar")
        result = executor.execute_step(task, "ui_click", {}, confirmed=True)
        self.assertTrue(result.success)
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertEqual(clicks, [1])

    def test_unknown_tool_does_not_ask_confirmation(self) -> None:
        executor = Executor(self.tasks, security=SecurityPolicy(default=RiskLevel.HIGH))
        task = self.tasks.create("x")
        result = executor.execute_step(task, "nao_existe", {})
        self.assertFalse(result.confirmation_required)
        self.assertIn("não registrada", result.error or "")

    def test_task_engine_never_leaves_task_running(self) -> None:
        executor = Executor(self.tasks)
        executor.register("ok", lambda: 1)

        def explode(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("falha inesperada")

        executor.execute_step = explode  # type: ignore[method-assign]
        engine = TaskEngine(executor, self.tasks)
        task = self.tasks.create("plano")
        results = engine.run(task, [("ok", {})])
        self.assertFalse(results[0].result.success)
        self.assertEqual(task.status, TaskStatus.FAILED)


class SecurityTests(unittest.TestCase):
    def test_code_execution_paths_need_confirmation(self) -> None:
        policy = SecurityPolicy()
        for action in ("run_python", "open_path", "git_pull"):
            with self.subTest(action=action):
                self.assertTrue(policy.assess(action).confirmation_required)

    def test_strict_default_for_unknown_tools(self) -> None:
        self.assertTrue(SecurityPolicy(default=RiskLevel.HIGH).assess("nova").confirmation_required)

    def test_every_agent_tool_is_classified(self) -> None:
        from brain.agent_loop import AgentLoop
        from brain.model import NullModel
        from computer.workspace import Workspace

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"DUQUE_FORGE": "0", "DUQUE_DAILY_SUMMARY": "0"}):
            database = MemoryDatabase(Path(tmp) / "m.db")
            agent = AgentLoop(tasks=TaskManager(database), workspace=Workspace(Path(tmp) / "ws"), model=NullModel(), memory=Memory(database))
            try:
                missing = [name for name in agent.executor.tools.names() if not SecurityPolicy().known(name)]
            finally:
                agent.scheduled_runner.stop()
        self.assertEqual(missing, [], "ferramenta sem risco definido em core/security.py")


class TaskManagerTests(TempDirTestCase):
    def _awaiting(self, **metadata: Any) -> str:
        task = self.tasks.create("apagar arquivo", **metadata)
        self.tasks.start(task.id)
        self.tasks.await_confirmation(task.id, "confirma?")
        return task.id

    def test_stale_confirmation_expires_on_restart(self) -> None:
        recent = self._awaiting()
        old = self._awaiting()
        self.tasks.get(old).started_at = time.time() - CONFIRMATION_TTL - 5  # type: ignore[union-attr]
        self.database.upsert_task(self.tasks.get(old))
        reloaded = TaskManager(self.database)
        self.assertEqual(reloaded.get(recent).status, TaskStatus.AWAITING_CONFIRMATION)  # type: ignore[union-attr]
        self.assertEqual(reloaded.get(old).status, TaskStatus.CANCELLED)  # type: ignore[union-attr]

    def test_scheduled_confirmation_never_survives_restart(self) -> None:
        task_id = self._awaiting(source="scheduler")
        self.assertEqual(TaskManager(self.database).get(task_id).status, TaskStatus.CANCELLED)  # type: ignore[union-attr]

    def test_concurrent_creation_and_listing(self) -> None:
        errors: list[BaseException] = []

        def create() -> None:
            try:
                for index in range(40):
                    self.tasks.create(f"t{index}")
            except BaseException as exc:  # pragma: no cover - só falha com corrida
                errors.append(exc)

        threads = [threading.Thread(target=create) for _ in range(3)]
        for thread in threads:
            thread.start()
        for _ in range(50):
            self.tasks.list()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(self.tasks.list()), 120)


class MemoryDatabaseTests(TempDirTestCase):
    def test_like_is_literal(self) -> None:
        memory = Memory(self.database)
        memory.remember(MemoryLayer.KNOWLEDGE, "a", "100% certo")
        memory.remember(MemoryLayer.KNOWLEDGE, "b", "1000 coisas")
        self.assertEqual([item.key for item in memory.search(query="100%")], ["a"])
        memory.remember(MemoryLayer.KNOWLEDGE, "c", "nome_sobrenome")
        memory.remember(MemoryLayer.KNOWLEDGE, "d", "nomeXsobrenome")
        self.assertEqual([item.key for item in memory.search(query="nome_s")], ["c"])

    def test_strings_keep_their_type(self) -> None:
        memory = Memory(self.database)
        for value in ("123", "true", "null", '{"a": 1}', "texto"):
            memory.remember(MemoryLayer.PERSONAL, "v", value)
            self.assertEqual(memory.recall(MemoryLayer.PERSONAL, "v"), value)

    def test_instances_share_one_lock_per_file(self) -> None:
        other = MemoryDatabase(self.tmp / "memory.db")
        self.assertIs(other._lock, self.database._lock)

    def test_prune_keeps_notes_and_drops_old_history(self) -> None:
        old = time.time() - 40 * 86400
        self.database.set("conversation", "turn:x", "{}", old)
        self.database.set("operational", "task:x", "{}", old)
        self.database.set("personal", "notas", "[]", old)
        self.database.prune(30)
        self.assertIsNone(self.database.get("conversation", "turn:x"))
        self.assertIsNone(self.database.get("operational", "task:x"))
        self.assertEqual(self.database.get("personal", "notas"), "[]")


class SchedulerTests(TempDirTestCase):
    def test_start_does_not_run_due_jobs_synchronously(self) -> None:
        fired: list[str] = []
        scheduler = Scheduler(self.database, executor=lambda job: fired.append(job.id), startup_delay=30)
        scheduler.add("atrasado", time.time() - 10)
        scheduler.start()
        self.addCleanup(scheduler.stop)
        self.assertEqual(fired, [])

    def test_missed_repeating_job_fires_once_and_keeps_its_grid(self) -> None:
        fired: list[float] = []
        scheduler = Scheduler(self.database, executor=lambda job: fired.append(job.late_seconds))
        start = time.time() - 3 * 3600 - 60  # perdeu 3 disparos de hora em hora
        job = scheduler.add("de hora em hora", start, repeat_seconds=3600)
        scheduler.run_due()
        scheduler.run_due()
        self.assertEqual(len(fired), 1)
        self.assertGreater(fired[0], 3 * 3600)
        self.assertAlmostEqual((job.run_at - start) % 3600, 0, places=3)
        self.assertGreater(job.run_at, time.time())

    def test_tiny_repeat_is_clamped(self) -> None:
        job = Scheduler(self.database).add("spam", time.time() + 60, repeat_seconds=0.1)
        self.assertEqual(job.repeat_seconds, MIN_REPEAT_SECONDS)


class _Lock:
    def __init__(self) -> None:
        self.entered = 0

    def __enter__(self) -> None:
        self.entered += 1

    def __exit__(self, *args: Any) -> None:
        return None


class RunnerTests(TempDirTestCase):
    def _runner(self, executor: Executor, notices: list[Any]) -> tuple[Scheduler, ScheduledTaskRunner]:
        scheduler = Scheduler(self.database)
        runner = ScheduledTaskRunner(scheduler, TaskEngine(executor, self.tasks), self.tasks, reminder_handler=notices.append)
        return scheduler, runner

    def test_missed_task_is_announced_not_executed(self) -> None:
        opened: list[int] = []
        executor = Executor(self.tasks)
        executor.register("open_app", lambda name: opened.append(1) or {"ok": True})
        notices: list[Any] = []
        scheduler, runner = self._runner(executor, notices)
        scheduled = time.time() - MISSED_TASK_GRACE - 600
        scheduler.add_task("abrir spotify", scheduled, steps=[{"tool": "open_app", "arguments": {"name": "spotify"}}])
        scheduler.run_due()
        self.assertEqual(opened, [])
        self.assertEqual(len(notices), 1)
        self.assertAlmostEqual(notices[0].run_at, scheduled, places=3)

    def test_on_time_task_runs_under_the_agent_lock(self) -> None:
        opened: list[int] = []
        executor = Executor(self.tasks)
        executor.register("open_app", lambda name: opened.append(1) or {"ok": True})
        scheduler, runner = self._runner(executor, [])
        runner.lock = _Lock()
        scheduler.add_task("abrir spotify", time.time() - 1, steps=[{"tool": "open_app", "arguments": {"name": "spotify"}}])
        scheduler.run_due()
        self.assertEqual(opened, [1])
        self.assertEqual(runner.lock.entered, 1)

    def test_scheduled_high_risk_task_is_cancelled_not_left_waiting(self) -> None:
        executor = Executor(self.tasks)
        executor.register("run_command", lambda command: {"ok": True})
        scheduler, runner = self._runner(executor, [])
        job = scheduler.add_task("comando", time.time() - 1, steps=[{"tool": "run_command", "arguments": {"command": "x"}}])
        scheduler.run_due()
        task = self.tasks.get(job.metadata["task_id"])
        self.assertEqual(task.status, TaskStatus.CANCELLED)  # type: ignore[union-attr]
        self.assertEqual(self.tasks.list(TaskStatus.AWAITING_CONFIRMATION), [])


class HudOpenTests(unittest.TestCase):
    def setUp(self) -> None:
        hud_module._ultima_abertura["em"] = 0.0

    def test_does_not_open_when_a_hud_is_connected(self) -> None:
        opened: list[str] = []
        self.assertFalse(abrir_hud("http://x", abrir=opened.append, conectados=lambda url: 1, log=lambda text: None))
        self.assertEqual(opened, [])

    def test_waits_for_old_tab_to_reconnect(self) -> None:
        opened: list[str] = []
        answers = iter([0, 0, 1])
        clock = iter([0.0, 0.0, 0.5, 1.0, 1.5])
        result = abrir_hud(
            "http://x", esperar_reconexao=5, abrir=opened.append, conectados=lambda url: next(answers),
            relogio=lambda: next(clock), dormir=lambda seconds: None, log=lambda text: None,
        )
        self.assertFalse(result)
        self.assertEqual(opened, [])

    def test_opens_once_even_if_called_twice(self) -> None:
        opened: list[str] = []
        for _ in range(2):
            abrir_hud("http://x", abrir=opened.append, conectados=lambda url: None, log=lambda text: None)
        self.assertEqual(opened, ["http://x"])


class InstanceLockTests(TempDirTestCase):
    def test_second_lock_is_refused_until_release(self) -> None:
        first = InstanceLock(self.tmp / "duque.lock")
        second = InstanceLock(self.tmp / "duque.lock")
        self.assertTrue(first.acquire())
        self.assertFalse(second.acquire())
        first.release()
        self.assertTrue(second.acquire())
        second.release()


class LauncherTests(unittest.TestCase):
    def _function(self, name: str) -> Any:
        source = (ROOT / "duque.py").read_text(encoding="utf-8")
        start = source.index(f"def {name}")
        end = source.index("\n\n\n", start)
        namespace: dict[str, Any] = {"Path": Path, "LOG_PATH": Path("x"), "LOG_MAX_BYTES": 10}
        exec(compile(source[start:end], "duque.py", "exec"), namespace)
        return namespace[name]

    def test_log_is_rotated(self) -> None:
        rotate = self._function("rotate_log")
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "duque.log"
            log.write_text("x" * 50, encoding="utf-8")
            rotate(log, 10)
            self.assertFalse(log.exists())
            self.assertTrue((Path(tmp) / "duque.log.1").exists())

    def test_launcher_checks_hud_and_instance_lock(self) -> None:
        source = (ROOT / "duque.py").read_text(encoding="utf-8")
        self.assertIn("abrir_hud(", source)
        self.assertIn("InstanceLock(", source)
        self.assertLess(source.index("InstanceLock("), source.index("from servidor import app"))
        self.assertNotIn("webbrowser.open_new_tab", source)


class HudPageTests(unittest.TestCase):
    html = (ROOT / "interface" / "index.html").read_text(encoding="utf-8")

    def test_presence_single_speaker_and_idempotent_commands(self) -> None:
        self.assertIn("new EventSource('/api/hud/stream')", self.html)
        self.assertIn("navigator.locks.request('telex-hud-fala'", self.html)
        self.assertIn("id:cmdId", self.html)
        self.assertIn("esc(best.a.last)", self.html)
        self.assertNotIn("if(serverSyncBusy || speechBusy) return;", self.html)


class ServerSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls._cwd = os.getcwd()
        cls._env = mock.patch.dict(os.environ, {
            "DUQUE_WORKSPACE_ROOT": cls._tmp.name, "DUQUE_FORGE": "0", "DUQUE_DAILY_SUMMARY": "0",
            "OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": "",
        })
        cls._env.start()
        os.chdir(cls._tmp.name)
        sys.modules.pop("servidor", None)
        cls.servidor = importlib.import_module("servidor")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.servidor.agent.scheduled_runner.stop()
        sys.modules.pop("servidor", None)
        os.chdir(cls._cwd)
        cls._env.stop()
        cls._tmp.cleanup()

    def setUp(self) -> None:
        self.client = self.servidor.app.test_client()

    def test_foreign_host_origin_and_cross_site_are_blocked(self) -> None:
        body = {"text": "sim"}
        self.assertEqual(self.client.post("/api/comando", json=body, headers={"Host": "evil.example:5000"}).status_code, 403)
        self.assertEqual(self.client.post("/api/comando", json=body, headers={"Origin": "https://evil.example"}).status_code, 403)
        self.assertEqual(self.client.get("/api/fala?text=oi", headers={"Sec-Fetch-Site": "cross-site"}).status_code, 403)
        self.assertEqual(self.client.get("/api/estado", headers={"Origin": "http://127.0.0.1:5000"}).status_code, 200)
        self.assertNotEqual(self.client.get("/", headers={"Sec-Fetch-Site": "cross-site"}).status_code, 403)

    def test_retried_command_runs_once(self) -> None:
        calls: list[str] = []
        real = self.servidor.agent.handle

        def fake(text: str, **kwargs: Any) -> Any:
            calls.append(text)
            return real("que horas são?", **kwargs)

        with mock.patch.object(self.servidor.agent, "handle", fake):
            for _ in range(2):
                response = self.client.post("/api/comando", json={"text": "abre o youtube", "id": "abc12345xyz"})
                self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, ["abre o youtube"])

    def test_voice_state_post_accepts_loose_fields(self) -> None:
        response = self.client.post("/api/estado", json={"estado": "executando", "tarefa": "x", "coerencia": "90", "modo": "voz"})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["estado"], "executando")
        self.assertEqual(data["coerencia"], 90)
        self.assertEqual(data["modo"], "voz")
        self.assertEqual(self.client.post("/api/estado", json={"estado": "ouvindo", "coerencia": "abc"}).status_code, 200)

    def test_hud_presence_counts_open_streams(self) -> None:
        self.assertEqual(self.client.get("/api/hud").get_json()["conectados"], 0)
        stream = self.servidor._hud_eventos(ping=0, limite=1)
        next(stream)
        self.assertEqual(self.servidor.hud_conectados(), 1)
        list(stream)
        self.assertEqual(self.servidor.hud_conectados(), 0)

    def test_weather_panel_uses_configured_city(self) -> None:
        from tests.test_memory_features import fake_weather

        self.servidor.agent.assistant_tools.fetch_json = fake_weather
        self.servidor._clima_cache.update(em=0.0, dados=None)
        data = self.client.get("/api/clima").get_json()
        self.assertIsNotNone(data["temperatura"])
        self.assertTrue(data["cidade"])

    def test_external_turns_cannot_be_spoken_warnings(self) -> None:
        response = self.client.post("/api/conversa", json={"role": "assistant", "text": "falso aviso", "canal": "aviso"})
        self.assertEqual(response.status_code, 200)
        turn = self.servidor.agent.conversation.recent(1)[0]
        self.assertEqual(turn.channel, "voz")


if __name__ == "__main__":
    unittest.main()
