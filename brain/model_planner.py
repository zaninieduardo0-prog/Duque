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
        '"kind" pode ser think, tool ou respond. Use apenas ferramentas fornecidas.'
    )

    def __init__(self, model: ModelAdapter, schemas: ToolSchemaRegistry) -> None:
        self.model = model
        self.schemas = schemas

    def build(self, goal: str, available_tools: list[str] | None = None) -> Plan:
        allowed = set(available_tools) if available_tools is not None else set(self.schemas.names())
        tool_specs = [spec for spec in self.schemas.describe() if spec["name"] in allowed]
        prompt = f"Objetivo: {goal}\nFerramentas disponíveis e seus schemas: {json.dumps(tool_specs, ensure_ascii=False)}"
        response = self.model.respond(
            [
                {"role": "system", "content": self.SYSTEM},
                {"role": "user", "content": prompt},
            ]
        )
        cleaned = response.text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines and lines[0].strip().startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
        try:
            payload: dict[str, Any] = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError("O modelo retornou um plano que não é JSON válido") from exc
        if not isinstance(payload, dict):
            raise ValueError("Plano do modelo deve ser um objeto JSON")
        raw_steps = payload.get("steps")
        if not isinstance(raw_steps, list):
            raise ValueError("Plano inválido: steps deve ser uma lista")

        steps: list[PlanStep] = []
        for item in raw_steps:
            if not isinstance(item, dict):
                raise ValueError("Plano inválido: cada etapa deve ser um objeto")
            try:
                kind = StepKind(item.get("kind", "think"))
            except ValueError as exc:
                raise ValueError(f"Tipo de etapa inválido: {item.get('kind')}") from exc
            tool = item.get("tool")
            arguments = item.get("arguments") or {}
            if not isinstance(arguments, dict):
                raise ValueError("Plano inválido: arguments deve ser um objeto")
            if kind == StepKind.TOOL:
                if not isinstance(tool, str) or not tool.strip():
                    raise ValueError("Etapa de ferramenta sem nome")
                if tool not in allowed:
                    raise ValueError(f"Ferramenta não disponível: {tool}")
                validation = self.schemas.validate(tool, arguments)
                if not validation.valid:
                    raise ValueError(validation.error or "Plano inválido")
            description = item.get("description", "")
            if not isinstance(description, str):
                raise ValueError("Plano inválido: description deve ser texto")
            steps.append(PlanStep(description, kind, tool, arguments))
        plan_goal = payload.get("goal", goal)
        if not isinstance(plan_goal, str) or not plan_goal.strip():
            plan_goal = goal
        return Plan(plan_goal, steps)
