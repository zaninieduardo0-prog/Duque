from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .events import EventType
from .executor import ExecutionResult, Executor
from .tasks import Task, TaskManager


@dataclass(slots=True)
class StepResult:
    index: int
    tool: str
    result: ExecutionResult


class TaskEngine:
    """Executa planos como um fluxo observável e verificável."""

    def __init__(self, executor: Executor, tasks: TaskManager | None = None, event_sink: Callable[..., Any] | None = None) -> None:
        self.executor = executor
        self.tasks = tasks or executor.tasks
        self.event_sink = event_sink

    def _emit(self, event: EventType, **data: Any) -> None:
        if self.event_sink:
            self.event_sink(event, **data)

    def run(self, task: Task, steps: list[tuple[str, dict[str, Any]]], *, confirmed: bool = False) -> list[StepResult]:
        self.tasks.start(task.id)
        results: list[StepResult] = []

        if not steps:
            reason = "O plano não contém etapas executáveis"
            self.tasks.fail(task.id, reason)
            self._emit(EventType.TASK_FAILED, task_id=task.id, error=reason)
            return results

        for index, (tool, arguments) in enumerate(steps, start=1):
            self._emit(EventType.TASK_STARTED, task_id=task.id, step=index, tool=tool)
            try:
                result = self.executor.execute_step(task, tool, arguments, confirmed=confirmed, manage_task=False)
            except Exception as exc:
                # Nunca deixar a tarefa presa em "running" por uma exceção inesperada
                # (ex.: falha ao gravar o estado, pausa interrompida).
                result = ExecutionResult(False, error=f"{type(exc).__name__}: {exc}")
            results.append(StepResult(index, tool, result))

            if not result.success:
                reason = result.error or "Falha desconhecida"
                if result.confirmation_required:
                    self.tasks.await_confirmation(task.id, reason)
                    return results
                self.tasks.fail(task.id, reason)
                self._emit(EventType.TASK_FAILED, task_id=task.id, step=index, tool=tool, error=reason)
                return results

        values = [item.result.value for item in results]
        self.tasks.complete(task.id, values)
        self._emit(EventType.TASK_FINISHED, task_id=task.id)
        return results

    @staticmethod
    def succeeded(results: list[StepResult]) -> bool:
        return bool(results) and all(item.result.success for item in results)
