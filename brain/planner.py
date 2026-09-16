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
    """Planejador inicial. O LLM poderá substituir esta heurística depois."""

    def build(self, goal: str, intent: str = "chat") -> Plan:
        if intent == "open_app":
            return Plan(goal, [PlanStep(f"Abrir o aplicativo solicitado: {goal}", StepKind.TOOL, "open_app")])
        if intent == "search":
            return Plan(goal, [PlanStep(f"Pesquisar: {goal}", StepKind.TOOL, "web_search")])
        if intent == "code":
            return Plan(goal, [
                PlanStep("Entender o objetivo e os requisitos", StepKind.THINK),
                PlanStep("Escrever ou modificar o código", StepKind.TOOL, "code_workspace"),
                PlanStep("Executar testes e verificar o resultado", StepKind.TOOL, "run_tests"),
                PlanStep("Relatar o resultado", StepKind.RESPOND),
            ])
        if intent == "file_operation":
            return Plan(goal, [PlanStep(f"Executar a operação de arquivo: {goal}", StepKind.TOOL, "file_manager")])
        if intent == "reminder":
            return Plan(goal, [PlanStep(f"Criar lembrete: {goal}", StepKind.TOOL, "scheduler")])
        if intent == "system":
            return Plan(goal, [PlanStep(f"Executar ação do sistema: {goal}", StepKind.TOOL, "system_control")])
        return Plan(goal, [PlanStep("Responder à solicitação", StepKind.RESPOND)])
