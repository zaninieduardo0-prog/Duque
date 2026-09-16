from __future__ import annotations

from dataclasses import dataclass

from core.events import EventType
from core.executor import Executor
from core.tasks import TaskManager, TaskStatus
from computer.perception import Perception, ScreenCapture
from computer.verification import Verification, VerificationStatus


@dataclass
class FakeImage:
    payload: bytes

    def tobytes(self) -> bytes:
        return self.payload


class FakeBackend:
    def __init__(self) -> None:
        self.payload = b"before"

    def capture(self) -> ScreenCapture:
        return ScreenCapture(FakeImage(self.payload), 100, 80)


def test_executor_marks_ui_action_success_when_screen_changes() -> None:
    backend = FakeBackend()
    verification = Verification(Perception(backend))
    tasks = TaskManager()
    events: list[EventType] = []
    executor = Executor(tasks, verification=verification, event_sink=lambda event, **_: events.append(event))
    executor.register("ui_click", lambda: backend.__setattr__("payload", b"after") or {"clicked": True})

    task = tasks.create("clicar")
    result = executor.execute_step(task, "ui_click", manage_task=False)

    assert result.success is True
    assert result.verification.status == VerificationStatus.CHANGED_UNCONFIRMED
    assert EventType.OBSERVATION_STARTED in events
    assert EventType.OBSERVATION_FINISHED in events
    assert EventType.VERIFICATION_STARTED in events
    assert EventType.VERIFICATION_FINISHED in events


def test_executor_marks_ui_action_failed_when_screen_does_not_change() -> None:
    backend = FakeBackend()
    verification = Verification(Perception(backend))
    tasks = TaskManager()
    executor = Executor(tasks, verification=verification)
    executor.register("ui_click", lambda: {"clicked": True})

    task = tasks.create("clicar")
    result = executor.execute_step(task, "ui_click", manage_task=False)

    assert result.success is False
    assert result.verification.status == VerificationStatus.NOT_CHANGED
    assert "não detectou mudança" in (result.error or "")
    assert task.status == TaskStatus.PENDING


def test_non_ui_tool_is_not_forced_through_visual_verification() -> None:
    backend = FakeBackend()
    verification = Verification(Perception(backend))
    tasks = TaskManager()
    executor = Executor(tasks, verification=verification)
    executor.register("plain", lambda: "ok")

    task = tasks.create("ação simples")
    result = executor.execute_step(task, "plain", manage_task=False)

    assert result.success is True
    assert result.value == "ok"
    assert result.verification is None
