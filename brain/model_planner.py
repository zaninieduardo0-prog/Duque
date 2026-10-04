from __future__ import annotations

import json

from .model import ModelAdapter, extract_json_object
from .planner import Plan, PlanStep, StepKind
from .tool_schema import ToolSchemaRegistry


class ModelPlanner:
    """Converte o pedido em um plano estruturado e validável, ou numa resposta direta."""

    SYSTEM = (
        "Você é o Duque, assistente pessoal do usuário (chame-o de Du), em português do Brasil. "
        "Decida se o pedido exige usar ferramentas ou se é só conversa. Retorne SOMENTE JSON:\n"
        '- conversa/pergunta/opinião: {"answer": "sua resposta natural e direta", "steps": []}\n'
        '- ação no computador: {"goal": "...", "steps": [{"description": "...", "kind": "tool", '
        '"tool": "nome", "arguments": {}}]}\n'
        "Regras: use só ferramentas fornecidas; nunca use ferramentas quando o usuário apenas "
        "comenta, pergunta como fazer algo ou nega ('não abra...'); não repita uma ação já feita "
        "no histórico; peça o mínimo de passos; não diga que é um modelo de linguagem."
    )

    def __init__(self, model: ModelAdapter, schemas: ToolSchemaRegistry) -> None:
        self.model = model
        self.schemas = schemas

    def build(
        self,
        goal: str,
        available_tools: list[str] | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> Plan:
        allowed = set(available_tools) if available_tools is not None else set(self.schemas.names())
        tool_specs = [spec for spec in self.schemas.describe() if spec["name"] in allowed]
        prompt = f"Pedido: {goal}\nFerramentas disponíveis e seus schemas: {json.dumps(tool_specs, ensure_ascii=False)}"
        messages = [{"role": "system", "content": self.SYSTEM}, *(history or []), {"role": "user", "content": prompt}]
        payload = extract_json_object(self.model.respond(messages).text)

        raw_steps = payload.get("steps", [])
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
        answer = payload.get("answer")
        return Plan(plan_goal, steps, answer.strip() if isinstance(answer, str) and answer.strip() else None)
