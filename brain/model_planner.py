from __future__ import annotations

import json
from typing import Any

from .model import ModelAdapter
from .planner import Plan, PlanStep, StepKind
from .tool_schema import ToolSchemaRegistry


class ModelPlanner:
    """Converte a intenção do modelo em um plano estruturado e validável."""

    SYSTEM = (
        "Você é o planejador de tarefas do Duque. Retorne SOMENTE JSON no formato "
        '{"goal": "...", "steps": [{"description":"...", "kind":"tool", '
        '"tool":"nome", "arguments":{}}]}. '
        "kind" pode ser think, tool ou respond. Use apenas ferramentas fornecidas."
    )

    def __init__(self, model: ModelAdapter, schemas: ToolSchemaRegistry) -> None:
        self.model = model
        self.schemas = schemas

    def build(self, goal: str, available_tools: list[str] | None = None) -> Plan:
        tools = available_tools or []
        prompt = f"Objetivo: {goal}\nFerramentas disponíveis: {json.dumps(tools, ensure_ascii=False)}"
        response = self.model.respond([{"role": "system", "content": self.SYSTEM}, {"role": "user", "content": prompt}])
        try:
            payload: dict[str, Any] = json.loads(response.text)
        except json.JSONDecodeError as exc:
            raise ValueError("O modelo retornou um plano que não é JSON válido") from exc

        steps: list[PlanStep] = []
        for item in payload.get("steps", []):
            kind = StepKind(item.get("kind", "think"))
            tool = item.get("tool")
            arguments = item.get("arguments") or {}
            if kind == StepKind.TOOL:
                if not tool:
                    raise ValueError("Etapa de ferramenta sem nome")
                validation = self.schemas.validate(tool, arguments)
                if not validation.valid:
                    raise ValueError(validation.error or "Plano inválido")
            steps.append(PlanStep(item.get("description", ""), kind, tool, arguments))
        return Plan(payload.get("goal", goal), steps)
