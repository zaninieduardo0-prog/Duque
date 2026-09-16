from __future__ import annotations

import time

from automation.runner import ScheduledTaskRunner
from automation.scheduler import Scheduler
from core.executor import Executor
from core.task_engine import TaskEngine
from core.tasks import TaskManager, TaskStatus
from memory.database import MemoryDatabase


def build_runtime(tmp_path):
    database = MemoryDatabase(tmp_path / "memory.db")
    tasks = TaskManager(database)
    executor = Executor(tasks)
    calls: list[str] = []

    def fake_tool(value: str) -> dict[str, str]:
        calls.append(value)
        return {"value": value}

    executor.register("fake_tool", fake_tool)
    engine = TaskEngine(executor, tasks)
    scheduler = Scheduler(database=database, poll_interval=0.05)
    runner = ScheduledTaskRunner(scheduler, engine, tasks)
    return database, tasks, scheduler, runner, calls


def test_due_scheduled_task_executes_and_persists(tmp_path):
    _, tasks, scheduler, runner, calls = build_runtime(tmp_path)
    task = tasks.create("Executar teste")
    job = scheduler.add_task_after(
        task.description,
        0,
        task_id=task.id,
        steps=[{"tool": "fake_tool", "arguments": {"value": "ok"}}],
    )

    assert scheduler.run_due() == 1
    assert calls == ["ok"]
    assert tasks.get(task.id).status == TaskStatus.COMPLETED
    assert job.enabled is False


def test_task_survives_restart_and_due_job_runs(tmp_path):
    database = MemoryDatabase(tmp_path / "memory.db")
    tasks = TaskManager(database)
    executor = Executor(tasks)
    calls: list[str] = []
    executor.register("fake_tool", lambda value: calls.append(value) or {"value": value})
    engine = TaskEngine(executor, tasks)

    task = tasks.create("Persistente")
    Scheduler(database=database).add_task_after(
        task.description,
        0,
        task_id=task.id,
        steps=[{"tool": "fake_tool", "arguments": {"value": "restart"}}],
    )

    tasks_after_restart = TaskManager(database)
    scheduler_after_restart = Scheduler(database=database)
    ScheduledTaskRunner(scheduler_after_restart, TaskEngine(executor, tasks_after_restart), tasks_after_restart)

    assert scheduler_after_restart.run_due() == 1
    assert calls == ["restart"]
    assert tasks_after_restart.get(task.id).status == TaskStatus.COMPLETED


def test_cancelled_job_does_not_execute(tmp_path):
    _, tasks, scheduler, runner, calls = build_runtime(tmp_path)
    task = tasks.create("Não executar")
    job = scheduler.add_task_after(
        task.description,
        0,
        task_id=task.id,
        steps=[{"tool": "fake_tool", "arguments": {"value": "cancelado"}}],
    )

    assert scheduler.cancel(job.id) is True
    assert scheduler.run_due() == 0
    assert calls == []
    assert tasks.get(task.id).status == TaskStatus.PENDING


def test_recurring_job_creates_a_new_task_execution(tmp_path):
    _, tasks, scheduler, runner, calls = build_runtime(tmp_path)
    task = tasks.create("Recorrente")
    job = scheduler.add_task_after(
        task.description,
        0,
        task_id=task.id,
        steps=[{"tool": "fake_tool", "arguments": {"value": "tick"}}],
        repeat_seconds=60,
    )

    assert scheduler.run_due() == 1
    first_task_id = job.metadata["task_id"]
    assert calls == ["tick"]
    assert tasks.get(first_task_id).status == TaskStatus.COMPLETED
    assert job.enabled is True

    job.run_at = time.time() - 1
    scheduler._save(job)
    assert scheduler.run_due() == 1

    second_task_id = job.metadata["task_id"]
    assert second_task_id != first_task_id
    assert calls == ["tick", "tick"]
    assert tasks.get(second_task_id).status == TaskStatus.COMPLETED
