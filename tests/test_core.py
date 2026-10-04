from __future__ import annotations

import unittest

from core.engine import DuqueEngine
from core.events import Event, EventBus, EventType
from core.executor import Executor
from core.security import RiskLevel, SecurityPolicy
from core.state import DuqueState, InvalidTransition, StateManager
from core.task_engine import TaskEngine
from core.tasks import TaskManager, TaskStatus
from tests.helpers import TempDirTestCase


class StateManagerTests(unittest.TestCase):
    def test_valid_transition_updates_snapshot(self) -> None:
        manager = StateManager()
        snapshot = manager.transition(DuqueState.LISTENING, activity="ouvindo")
        self.assertEqual(snapshot.state, DuqueState.LISTENING)
        self.assertEqual(manager.snapshot().activity, "ouvindo")

    def test_invalid_transition_raises(self) -> None:
        manager = StateManager(DuqueState.SLEEPING)
        with self.assertRaises(InvalidTransition):
            manager.transition(DuqueState.EXECUTING)

    def test_force_allows_any_transition(self) -> None:
        manager = StateManager(DuqueState.SLEEPING)
        snapshot = manager.transition(DuqueState.EXECUTING, force=True)
        self.assertEqual(snapshot.state, DuqueState.EXECUTING)

    def test_coherence_is_clamped(self) -> None:
        manager = StateManager()
        self.assertEqual(manager.transition(DuqueState.STANDBY, coherence=500).coherence, 100)
        self.assertEqual(manager.transition(DuqueState.STANDBY, coherence=-5).coherence, 0)

    def test_failing_listener_does_not_break_transition(self) -> None:
        manager = StateManager()

        def broken(_snapshot) -> None:
            raise RuntimeError("listener quebrado")

        manager.subscribe(broken)
        self.assertEqual(manager.transition(DuqueState.LISTENING).state, DuqueState.LISTENING)


class EventBusTests(unittest.TestCase):
    def test_typed_and_wildcard_subscribers_receive_events(self) -> None:
        bus = EventBus()
        typed: list[Event] = []
        wildcard: list[Event] = []
        bus.subscribe(EventType.TASK_STARTED, typed.append)
        bus.subscribe(None, wildcard.append)

        bus.emit(Event(EventType.TASK_STARTED, {"tool": "x"}))
        bus.emit(Event(EventType.ERROR))

        self.assertEqual([event.type for event in typed], [EventType.TASK_STARTED])
        self.assertEqual([event.type for event in wildcard], [EventType.TASK_STARTED, EventType.ERROR])

    def test_unsubscribe_stops_delivery(self) -> None:
        bus = EventBus()
        received: list[Event] = []
        unsubscribe = bus.subscribe(EventType.ERROR, received.append)
        unsubscribe()
        bus.emit(Event(EventType.ERROR))
        self.assertEqual(received, [])


class EngineTests(unittest.TestCase):
    def test_sleep_and_wake_emit_events_and_change_state(self) -> None:
        engine = DuqueEngine()
        seen: list[EventType] = []
        engine.events.subscribe(None, lambda event: seen.append(event.type))

        engine.start()
        engine.sleep()
        self.assertFalse(engine.running)
        self.assertEqual(engine.state.snapshot().state, DuqueState.SLEEPING)

        engine.wake()
        self.assertTrue(engine.running)
        self.assertIn(EventType.DUQUE_SLEEP, seen)
        self.assertEqual(seen.count(EventType.DUQUE_WAKE), 2)


class SecurityPolicyTests(unittest.TestCase):
    def test_high_risk_actions_require_confirmation(self) -> None:
        policy = SecurityPolicy()
        for action in ("git_push", "delete_file", "run_command", "kill_process", "write_any_file"):
            with self.subTest(action=action):
                assessed = policy.assess(action)
                self.assertEqual(assessed.risk, RiskLevel.HIGH)
                self.assertTrue(assessed.confirmation_required)

    def test_low_risk_actions_run_directly(self) -> None:
        assessed = SecurityPolicy().assess("read_file")
        self.assertFalse(assessed.confirmation_required)

    def test_unknown_tools_require_confirmation(self) -> None:
        assessed = SecurityPolicy().assess("ferramenta_nova")
        self.assertEqual(assessed.risk, RiskLevel.HIGH)
        self.assertTrue(assessed.confirmation_required)


class TaskManagerTests(TempDirTestCase):
    def test_lifecycle_is_persisted(self) -> None:
        task = self.tasks.create("tarefa de teste", origem="teste")
        self.tasks.start(task.id)
        self.tasks.complete(task.id, {"ok": True})

        reloaded = TaskManager(self.database).get(task.id)
        assert reloaded is not None
        self.assertEqual(reloaded.status, TaskStatus.COMPLETED)
        self.assertEqual(reloaded.result, {"ok": True})
        self.assertEqual(reloaded.metadata["origem"], "teste")

    def test_running_task_is_recovered_as_pending_after_restart(self) -> None:
        task = self.tasks.create("interrompida")
        self.tasks.start(task.id)

        reloaded = TaskManager(self.database).get(task.id)
        assert reloaded is not None
        self.assertEqual(reloaded.status, TaskStatus.PENDING)
        self.assertIn("encerrado", reloaded.error or "")

    def test_completed_task_cannot_restart(self) -> None:
        task = self.tasks.create("feita")
        self.tasks.start(task.id)
        self.tasks.complete(task.id)
        with self.assertRaises(RuntimeError):
            self.tasks.start(task.id)


class ExecutorTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.executor = Executor(self.tasks, security=SecurityPolicy(default=RiskLevel.MEDIUM))

    def test_successful_tool_completes_task(self) -> None:
        self.executor.register("somar", lambda a, b: a + b)
        task = self.tasks.create("somar")
        result = self.executor.execute_step(task, "somar", {"a": 2, "b": 3})
        self.assertTrue(result.success)
        self.assertEqual(result.value, 5)
        self.assertEqual(task.status, TaskStatus.COMPLETED)

    def test_exception_becomes_failed_result(self) -> None:
        def explode() -> None:
            raise ValueError("boom")

        self.executor.register("explodir", explode)
        task = self.tasks.create("explodir")
        result = self.executor.execute_step(task, "explodir")
        self.assertFalse(result.success)
        self.assertIn("boom", result.error or "")
        self.assertEqual(task.status, TaskStatus.FAILED)

    def test_tool_reporting_failure_is_not_success(self) -> None:
        """Executar uma ferramenta não significa sucesso: o retorno precisa confirmar."""
        self.executor.register("falha_silenciosa", lambda: {"success": False, "stderr": "erro real"})
        task = self.tasks.create("falha")
        result = self.executor.execute_step(task, "falha_silenciosa")
        self.assertFalse(result.success)
        self.assertEqual(result.error, "erro real")

    def test_high_risk_tool_requires_confirmation_and_is_not_called(self) -> None:
        calls: list[str] = []
        self.executor.register("git_push", lambda: calls.append("push"))
        task = self.tasks.create("push")

        blocked = self.executor.execute_step(task, "git_push")
        self.assertFalse(blocked.success)
        self.assertTrue(blocked.confirmation_required)
        self.assertEqual(calls, [])

        allowed = self.executor.execute_step(task, "git_push", confirmed=True)
        self.assertTrue(allowed.success)
        self.assertEqual(calls, ["push"])

    def test_unregistered_tool_fails(self) -> None:
        task = self.tasks.create("inexistente")
        result = self.executor.execute_step(task, "nao_existe")
        self.assertFalse(result.success)
        self.assertIn("não registrada", result.error or "")


class TaskEngineTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.executor = Executor(self.tasks, security=SecurityPolicy(default=RiskLevel.MEDIUM))
        self.events: list[tuple[EventType, dict]] = []
        self.engine = TaskEngine(self.executor, event_sink=lambda event, **data: self.events.append((event, data)))

    def test_runs_all_steps_and_emits_events(self) -> None:
        self.executor.register("a", lambda: 1)
        self.executor.register("b", lambda: 2)
        task = self.tasks.create("plano")

        results = self.engine.run(task, [("a", {}), ("b", {})])

        self.assertTrue(TaskEngine.succeeded(results))
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertEqual(task.result, [1, 2])
        self.assertEqual([event for event, _ in self.events].count(EventType.TASK_STARTED), 2)
        self.assertEqual(self.events[-1][0], EventType.TASK_FINISHED)

    def test_stops_at_first_failure(self) -> None:
        calls: list[str] = []
        self.executor.register("ok", lambda: calls.append("ok"))
        self.executor.register("ruim", lambda: {"success": False, "error": "falhou"})
        task = self.tasks.create("plano")

        results = self.engine.run(task, [("ruim", {}), ("ok", {})])

        self.assertFalse(TaskEngine.succeeded(results))
        self.assertEqual(calls, [])
        self.assertEqual(task.status, TaskStatus.FAILED)

    def test_confirmation_pauses_task(self) -> None:
        self.executor.register("git_push", lambda: None)
        task = self.tasks.create("plano")
        self.engine.run(task, [("git_push", {})])
        self.assertEqual(task.status, TaskStatus.AWAITING_CONFIRMATION)

    def test_empty_plan_fails(self) -> None:
        task = self.tasks.create("vazio")
        self.assertEqual(self.engine.run(task, []), [])
        self.assertEqual(task.status, TaskStatus.FAILED)


if __name__ == "__main__":
    unittest.main()
