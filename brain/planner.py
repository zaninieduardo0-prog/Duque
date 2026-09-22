from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StepKind(str, Enum):
    THINK = "think"
    TOOL = "tool"
    RESPOND = "respond"


@dataclass(slots=True)
class PlanStep:
    description: str
    kind: StepKind = StepKind.THINK
    tool: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Plan:
    goal: str
    steps: list[PlanStep] = field(default_factory=list)


class Planner:
    """Planejador heurístico seguro até o planejador orientado por modelo entrar."""

    @staticmethod
    def _app_name(goal: str) -> str:
        value = goal.strip()
        prefixes = (
            "abrir o aplicativo ",
            "abrir aplicativo ",
            "abrir o ",
            "abrir ",
        )
        lowered = value.casefold()
        for prefix in prefixes:
            if lowered.startswith(prefix):
                return value[len(prefix):].strip()
        return value

    def build(self, goal: str, intent: str = "chat") -> Plan:
        if intent == "open_app":
            app_name = self._app_name(goal)
            return Plan(goal, [PlanStep(
                f"Abrir o aplicativo solicitado: {app_name}",
                StepKind.TOOL,
                "open_app",
                {"name": app_name},
            )])
        if intent == "search":
            return Plan(goal, [PlanStep(f"Pesquisar: {goal}", StepKind.TOOL, "web_search", {"query": goal})])
        if intent == "code":
            return Plan(goal, [
                PlanStep("Entender o objetivo e os requisitos", StepKind.THINK),
                PlanStep("Listar o workspace antes da alteração", StepKind.TOOL, "list_files"),
                PlanStep("Escrever ou modificar o código", StepKind.THINK),
                PlanStep("Executar o código ou teste solicitado", StepKind.THINK),
                PlanStep("Relatar o resultado", StepKind.RESPOND),
            ])
        if intent == "file_operation":
            return Plan(goal, [PlanStep(f"Executar a operação de arquivo: {goal}", StepKind.TOOL, "file_manager", {"operation": goal})])
        if intent == "reminder":
            return Plan(goal, [PlanStep(f"Criar lembrete: {goal}", StepKind.TOOL, "scheduler", {"description": goal})])
        if intent == "system":
            return Plan(goal, [PlanStep(f"Executar ação do sistema: {goal}", StepKind.TOOL, "system_control", {"action": goal})])
        return Plan(goal, [PlanStep("Responder à solicitação", StepKind.RESPOND)])
