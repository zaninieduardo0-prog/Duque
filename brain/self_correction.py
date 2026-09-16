from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from core.task_engine import StepResult, TaskEngine
from core.tasks import Task


@dataclass(slots=True)
class CorrectionReport:
    success: bool
    attempts: int
    results: list[StepResult]
    last_error: str | None = None


class SelfCorrection:
    """Laço simples de executar -> observar erro -> pedir nova tentativa."""

    def __init__(self, task_engine: TaskEngine) -> None:
        self.task_engine = task_engine

    def run(
        self,
        task: Task,
        steps_factory: Callable[[str | None, int], list[tuple[str, dict[str, Any] | None]]],
        *,
        max_attempts: int = 3,
        confirmed: bool = False,
    ) -> CorrectionReport:
        error: str | None = None
        all_results: list[StepResult] = []

        for attempt in range(1, max(1, max_attempts) + 1):
            steps = steps_factory(error, attempt)
            results = self.task_engine.run(task, steps, confirmed=confirmed)
            all_results.extend(results)

            if self.task_engine.succeeded(results):
                return CorrectionReport(True, attempt, all_results)

            failed = next((item for item in reversed(results) if not item.result.success), None)
            error = failed.result.error if failed else "Falha sem detalhes"

        return CorrectionReport(False, max(1, max_attempts), all_results, error)
