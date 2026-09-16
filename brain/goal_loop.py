from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .agent_state import AgentContext


@dataclass(slots=True, frozen=True)
class GoalStep:
    """Ação planejada com condição opcional de sucesso."""

    description: str
    tool: str
    arguments: dict[str, Any]
    success_condition: dict[str, Any] | None = None


@dataclass(slots=True, frozen=True)
class GoalStepResult:
    index: int
    step: GoalStep
    success: bool
    value: Any = None
    error: str | None = None
    verification: Any = None


@dataclass(slots=True, frozen=True)
class GoalRunResult:
    success: bool
    context: AgentContext
    steps: list[GoalStepResult]
    reason: str | None = None


class GoalLoop:
    """Loop observe -> decide -> act -> verify, sem depender de voz ou HUD."""

    def __init__(
        self,
        executor: Any,
        *,
        observer: Callable[[], dict[str, Any]] | None = None,
        planner: Callable[[AgentContext], list[GoalStep]] | None = None,
        max_steps: int = 12,
    ) -> None:
        self.executor = executor
        self.observer = observer
        self.planner = planner
        self.max_steps = max(1, max_steps)

    def run(self, context: AgentContext, steps: list[GoalStep] | None = None, *, confirmed: bool = False) -> GoalRunResult:
        planned = steps
        results: list[GoalStepResult] = []

        for _ in range(self.max_steps):
            if planned is None:
                if self.planner is None:
                    return GoalRunResult(False, context, results, "Nenhum planejador foi configurado")
                planned = self.planner(context)
            if not planned:
                return GoalRunResult(True, context, results)

            step = planned.pop(0)
            if self.observer is not None:
                context.observe(self.observer())

            task = self.executor.tasks.get(context.task_id)
            if task is None:
                return GoalRunResult(False, context, results, "Tarefa do contexto não encontrada")

            result = self.executor.execute_step(task, step.tool, step.arguments, confirmed=confirmed, manage_task=False)
            item = GoalStepResult(
                len(results) + 1,
                step,
                result.success,
                result.value,
                result.error,
                result.verification,
            )
            results.append(item)

            if not result.success:
                context.record_failure(result.error or "Falha desconhecida")
                return GoalRunResult(False, context, results, result.error)

            context.record_step(tool=step.tool, arguments=step.arguments, result=result.value)
            planned = planned

        return GoalRunResult(False, context, results, f"Limite de {self.max_steps} passos atingido")
