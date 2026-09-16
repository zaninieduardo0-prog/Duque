from core.engine import DuqueEngine
from core.events import EventType
from core.executor import Executor
from core.task_engine import TaskEngine
from core.tasks import TaskManager, TaskStatus


def test_task_engine_runs_multiple_steps():
    engine = DuqueEngine()
    tasks = TaskManager()
    executor = Executor(tasks)
    values = []

    executor.register("append", lambda value: values.append(value) or value)
    task_engine = TaskEngine(executor, event_sink=engine.emit)
    task = tasks.create("teste")

    results = task_engine.run(task, [("append", {"value": "a"}), ("append", {"value": "b"})])

    assert task.status == TaskStatus.COMPLETED
    assert values == ["a", "b"]
    assert task.result == ["a", "b"]
    assert task_engine.succeeded(results)


def test_task_engine_stops_on_failure():
    tasks = TaskManager()
    executor = Executor(tasks)
    calls = []
    executor.register("ok", lambda: calls.append("ok"))
    executor.register("fail", lambda: (_ for _ in ()).throw(RuntimeError("quebrou")))

    task_engine = TaskEngine(executor)
    task = tasks.create("falha")
    results = task_engine.run(task, [("ok", None), ("fail", None), ("ok", None)])

    assert task.status == TaskStatus.FAILED
    assert calls == ["ok"]
    assert len(results) == 2
    assert not task_engine.succeeded(results)
    assert "quebrou" in (task.error or "")
