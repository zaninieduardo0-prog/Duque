from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from core.executor import Executor, ExecutionResult
from .agent_state import AgentContext
from .model import ModelAdapter
from .tool_schema import ToolSchemaRegistry


@dataclass(slots=True)
class AutonomousResult:
    success: bool
    message: str
    steps: int = 0
    executions: list[ExecutionResult] = field(default_factory=list)
    error: str | None = None


class AutonomousLoop:
    """Loop boundedo: observa -> decide -> executa -> devolve resultado ao modelo."""

    SYSTEM = (
        "Você é o agente operacional do Duque. Trabalhe em ciclos curtos. "
        "Escolha SOMENTE uma ação por ciclo e use apenas ferramentas disponíveis. "
        "Retorne SOMENTE JSON válido. Formato de ferramenta: "
        '{"action":"tool","tool":"nome","arguments":{},"reason":"..."}. '
        "Formato de conclusão: {"action":"finish","message":"..."}. '
        "Se uma ferramenta falhar, analise o erro e tente uma abordagem diferente. "
        "Nunca invente resultado de ferramenta. Não diga que concluiu sem evidência."
    )

    def __init__(self, model: ModelAdapter, executor: Executor, schemas: ToolSchemaRegistry, *, max_steps: int = 12) -> None:
        self.model = model
        self.executor = executor
        self.schemas = schemas
        self.max_steps = max(1, max_steps)

    def run(self, context: AgentContext, *, confirmed: bool = False) -> AutonomousResult:
        task = self.executor.tasks.get(context.task_id)
        if task is None:
            return AutonomousResult(False, "", error="Tarefa do contexto não encontrada")

        messages: list[dict[str, str]] = [
            {"role": "system", "content": self.SYSTEM},
            {"role": "user", "content": self._initial_prompt(context)},
        ]
        executions: list[ExecutionResult] = []

        for step_number in range(1, self.max_steps + 1):
            response = self.model.respond(messages)
            action = self._parse_action(response.text)

            if action["action"] == "finish":
                message = str(action.get("message", "Tarefa finalizada."))
                return AutonomousResult(True, message, step_number - 1, executions)

            tool = str(action.get("tool", ""))
            arguments = action.get("arguments") or {}
            validation = self.schemas.validate(tool, arguments)
            if not validation.valid:
                error = validation.error or "Ação inválida"
                context.record_failure(error)
                messages.append({"role": "user", "content": f"AÇÃO REJEITADA: {error}"})
                continue

            result = self.executor.execute_step(task, tool, arguments, confirmed=confirmed, manage_task=False)
            executions.append(result)
            if result.confirmation_required:
                return AutonomousResult(False, "Preciso da sua confirmação antes de executar essa ação.", step_number, executions, result.error)

            if result.success:
                context.record_step(tool=tool, arguments=arguments, result=self._safe_result(result.value))
                feedback = {"success": True, "tool": tool, "result": self._safe_result(result.value)}
            else:
                error = result.error or "Falha desconhecida"
                context.record_failure(error)
                feedback = {"success": False, "tool": tool, "error": error}

            messages.append({"role": "assistant", "content": json.dumps(action, ensure_ascii=False, default=str)})
            messages.append({"role": "user", "content": "RESULTADO DA FERRAMENTA: " + json.dumps(feedback, ensure_ascii=False, default=str)})

        return AutonomousResult(False, "", self.max_steps, executions, f"Limite de {self.max_steps} passos atingido")

    def _initial_prompt(self, context: AgentContext) -> str:
        return (
            f"Objetivo: {context.goal}\n"
            f"Ferramentas disponíveis: {json.dumps(self.schemas.names(), ensure_ascii=False)}\n"
            "Comece pela ação mínima necessária para avançar."
        )

    def _parse_action(self, text: str) -> dict[str, Any]:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("O modelo retornou uma ação que não é JSON válido") from exc
        if not isinstance(payload, dict):
            raise ValueError("Ação do modelo deve ser um objeto JSON")
        action = payload.get("action")
        if action not in {"tool", "finish"}:
            raise ValueError(f"Ação desconhecida: {action}")
        if action == "tool" and not isinstance(payload.get("arguments", {}), dict):
            raise ValueError("arguments deve ser um objeto")
        return payload

    @staticmethod
    def _safe_result(value: Any) -> Any:
        try:
            json.dumps(value)
            return value
        except (TypeError, ValueError):
            return str(value)
