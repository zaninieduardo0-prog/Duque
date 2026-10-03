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


# Ações com efeito visível (abrir app, site, mensagem): repetir depois de uma
# falha abria a mesma coisa várias vezes. Elas rodam uma vez só.
NO_RETRY_TOOLS = frozenset({
    "open_app", "open_url", "open_path", "google_search", "open_search_result",
    "whatsapp_message", "media_control", "play_media", "spotify_play",
})


class SelfCorrection:
    """Laço simples de executar -> observar erro -> pedir nova tentativa."""

    def __init__(self, task_engine: TaskEngine) -> None:
        self.task_engine = task_engine

    def run(
        self,
        task: Task,
        steps_factory: Callable[[str | None, int], list[tuple[str, dict[str, Any]]]],
        *,
        max_attempts: int = 3,
        confirmed: bool = False,
    ) -> CorrectionReport:
        error: str | None = None
        all_results: list[StepResult] = []
        attempts_limit = max(1, max_attempts)

        for attempt in range(1, attempts_limit + 1):
            steps = steps_factory(error, attempt)
            if not steps:
                return CorrectionReport(False, attempt, all_results, "O plano não contém etapas executáveis")

            results = self.task_engine.run(task, steps, confirmed=confirmed)
            all_results.extend(results)

            if self.task_engine.succeeded(results):
                return CorrectionReport(True, attempt, all_results)

            failed = next((item for item in reversed(results) if not item.result.success), None)
            error = failed.result.error if failed else "Falha sem detalhes"

            if failed and failed.result.confirmation_required:
                return CorrectionReport(False, attempt, all_results, error)
            if any(item.tool in NO_RETRY_TOOLS for item in results):
                return CorrectionReport(False, attempt, all_results, error)

        return CorrectionReport(False, attempts_limit, all_results, error)

