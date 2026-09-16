from __future__ import annotations

import tempfile
from pathlib import Path

from core.engine import DuqueEngine
from core.events import EventType
from core.executor import Executor
from core.tasks import TaskManager, TaskStatus
from computer.code_tools import CodeTools
from computer.workspace import Workspace


def test_engine_lifecycle() -> None:
    engine = DuqueEngine()
    events: list[EventType] = []
    engine.events.subscribe(None, lambda event: events.append(event.type))

    engine.start()
    assert engine.running
    engine.sleep()
    assert not engine.running
    engine.wake()
    assert engine.running
    assert EventType.DUQUE_WAKE in events
    assert EventType.DUQUE_SLEEP in events


def test_task_has_one_lifecycle_for_multiple_steps() -> None:
    tasks = TaskManager()
    executor = Executor(tasks)
    values: list[int] = []
    executor.register("step", lambda value: values.append(value) or value)

    task = tasks.create("duas etapas")
    results = executor.execute_task(task, [("step", {"value": 1}), ("step", {"value": 2})])

    assert all(result.success for result in results)
    assert values == [1, 2]
    assert task.status == TaskStatus.COMPLETED
    assert task.result == [1, 2]


def test_workspace_blocks_path_escape() -> None:
    with tempfile.TemporaryDirectory() as directory:
        workspace = Workspace(directory)
        workspace.write("app.py", "print('ok')")
        assert workspace.read("app.py").content == "print('ok')"
        try:
            workspace.read("../outside.txt")
        except PermissionError:
            pass
        else:
            raise AssertionError("workspace aceitou caminho fora da raiz")


def test_run_python_in_workspace() -> None:
    with tempfile.TemporaryDirectory() as directory:
        workspace = Workspace(Path(directory))
        workspace.write("teste.py", "print('funcionando')")
        result = CodeTools(workspace).run_python("teste.py")
        assert result["success"] is True
        assert "funcionando" in result["stdout"]
