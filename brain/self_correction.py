from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from core.task_engine import StepResult, TaskEngine
from core.tasks import Task


@dataclass(slots=True)
class CorrectionReport:
    success: bool
    attempts: int
    results: list[StepResult]
    last_error: str | None = None
    # Etapas da última tentativa (as que realmente rodaram), para retomar uma
    # confirmação exatamente do ponto em que parou.
    last_steps: list[tuple[str, dict[str, Any]]] = field(default_factory=list)


# Ferramentas com efeito visível que não devem ser repetidas numa nova
# tentativa: reabrir empilha janelas/abas e redigitar duplica texto/cliques.
OPENING_TOOLS = frozenset({"open_app", "open_url", "open_path", "open_search_result"})
UI_TOOLS = frozenset({"ui_click", "ui_type_text", "ui_press", "ui_hotkey", "screen_click_text"})
# Comandos que rodaram e devolveram um resultado (ex.: testes falhando) já são a
# resposta; repeti-los só gasta tempo e repete efeitos colaterais.
COMMAND_TOOLS = frozenset({"run_tests", "run_python", "run_command"})


def _step_key(tool: str, arguments: dict[str, Any]) -> tuple[str, str]:
    return tool, repr(sorted(arguments.items()))


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
        opened: set[tuple[str, str]] = set()

        for attempt in range(1, attempts_limit + 1):
            steps = [
                (tool, arguments)
                for tool, arguments in steps_factory(error, attempt)
                if _step_key(tool, arguments) not in opened
            ]
            if not steps:
                if attempt > 1:
                    return CorrectionReport(False, attempt, all_results, error)
                return CorrectionReport(False, attempt, all_results, "O plano não contém etapas executáveis")

            # A confirmação do usuário vale só para o plano que ele aprovou; um
            # plano corrigido pelo modelo precisa pedir confirmação de novo.
            results = self.task_engine.run(task, steps, confirmed=confirmed and attempt == 1)
            all_results.extend(results)
            for item, (tool, arguments) in zip(results, steps):
                ran = item.result.success or item.result.verification is not None
                if (tool in OPENING_TOOLS and item.result.success) or (tool in UI_TOOLS and ran):
                    opened.add(_step_key(tool, arguments))

            if self.task_engine.succeeded(results):
                return CorrectionReport(True, attempt, all_results, last_steps=steps)

            failed = next((item for item in reversed(results) if not item.result.success), None)
            error = failed.result.error if failed else "Falha sem detalhes"

            if failed and failed.result.confirmation_required:
                return CorrectionReport(False, attempt, all_results, error, last_steps=steps)
            if failed and failed.tool in COMMAND_TOOLS and failed.result.value is not None:
                return CorrectionReport(False, attempt, all_results, error, last_steps=steps)

        return CorrectionReport(False, attempts_limit, all_results, error)
