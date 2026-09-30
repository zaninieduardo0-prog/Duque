from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from core.events import EventType
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
    pending_tool: str | None = None
    pending_arguments: dict[str, Any] | None = None


class AutonomousLoop:
    """Agente limitado: observa, decide, executa, recebe evidência e replaneja."""

    SYSTEM = (
        "Você é o agente operacional do Duque. Trabalhe em ciclos curtos. "
        "Escolha SOMENTE uma ação por ciclo e use apenas ferramentas disponíveis. "
        "Retorne SOMENTE JSON válido: "
        '{"action":"tool","tool":"nome","arguments":{},"reason":"..."} ou '
        '{"action":"finish","message":"..."}. '
        "Analise todos os resultados antes da próxima ação. Se algo falhar, corrija ou escolha outra abordagem. "
        "Nunca invente resultados e nunca declare sucesso sem evidência. "
        "Quando a tarefa envolver interface, prefira observar/localizar antes de clicar ou digitar. "
        "Quando a tarefa envolver desenvolvimento do próprio projeto, inspecione o código, faça uma alteração por vez, execute o código afetado, analise o resultado e use git_diff para verificar o que realmente mudou antes de concluir. "
        "Só finalize depois que os resultados das ferramentas fornecerem evidência suficiente de conclusão."
    )

    def __init__(
        self,
        model: ModelAdapter,
        executor: Executor,
        schemas: ToolSchemaRegistry,
        *,
        max_steps: int = 12,
        observer: Callable[[], dict[str, Any]] | None = None,
        event_sink: Callable[..., Any] | None = None,
    ) -> None:
        self.model = model
        self.executor = executor
        self.schemas = schemas
        self.max_steps = max(1, max_steps)
        self.observer = observer
        self.event_sink = event_sink

    def _emit(self, event: EventType, **data: Any) -> None:
        if self.event_sink:
            self.event_sink(event, **data)

    def run(
        self,
        context: AgentContext,
        *,
        confirmed_action: tuple[str, dict[str, Any]] | None = None,
    ) -> AutonomousResult:
        task = self.executor.tasks.get(context.task_id)
        if task is None:
            return AutonomousResult(False, "", error="Tarefa do contexto não encontrada")

        messages: list[dict[str, str]] = [
            {"role": "system", "content": self.SYSTEM},
            {"role": "user", "content": self._initial_prompt(context)},
        ]
        executions: list[ExecutionResult] = []
        had_successful_tool = False
        last_tool_succeeded = False

        for step_number in range(1, self.max_steps + 1):
            if self.observer is not None:
                try:
                    observation = self.observer()
                    context.observe(observation)
                    messages.append({"role": "user", "content": "OBSERVAÇÃO ATUAL: " + self._safe_json(observation)})
                except Exception as exc:
                    context.record_failure(f"Falha de observação: {type(exc).__name__}: {exc}")

            try:
                response = self.model.respond(messages)
                action = self._parse_action(response.text)
            except Exception as exc:
                error = f"Falha ao interpretar decisão do modelo: {type(exc).__name__}: {exc}"
                context.record_failure(error)
                messages.append({"role": "user", "content": "AÇÃO REJEITADA: " + error + ". Retorne somente um objeto JSON válido no formato solicitado."})
                continue

            if action["action"] == "finish":
                message = str(action.get("message", "Tarefa finalizada.")).strip()
                if not message:
                    messages.append({"role": "user", "content": "AÇÃO REJEITADA: a mensagem de conclusão está vazia. Continue trabalhando."})
                    continue
                if context.goal.strip() and (not had_successful_tool or not last_tool_succeeded):
                    reason = (
                        "ainda não existe evidência de execução"
                        if not had_successful_tool
                        else "a última ferramenta falhou e a tarefa precisa ser reavaliada"
                    )
                    messages.append({"role": "user", "content": f"AÇÃO REJEITADA: {reason}. Execute uma ferramenta ou corrija a abordagem antes de concluir."})
                    continue
                self._emit(EventType.TASK_FINISHED, task_id=task.id, steps=step_number - 1)
                return AutonomousResult(True, message, step_number - 1, executions)

            tool = str(action.get("tool", "")).strip()
            arguments = action.get("arguments") or {}
            validation = self.schemas.validate(tool, arguments)
            if not validation.valid:
                error = validation.error or "Ação inválida"
                context.record_failure(error)
                messages.append({"role": "assistant", "content": self._safe_json(action)})
                messages.append({"role": "user", "content": f"AÇÃO REJEITADA: {error}. Escolha uma ferramenta válida e tente novamente."})
                continue

            self._emit(EventType.TASK_STARTED, task_id=task.id, step=step_number, tool=tool)
            action_confirmed = confirmed_action is not None and tool == confirmed_action[0] and arguments == confirmed_action[1]
            if action_confirmed:
                confirmed_action = None
            result = self.executor.execute_step(task, tool, arguments, confirmed=action_confirmed, manage_task=False)
            executions.append(result)
            if result.confirmation_required:
                return AutonomousResult(
                    False,
                    "Preciso da sua confirmação antes de executar essa ação.",
                    step_number,
                    executions,
                    result.error,
                    pending_tool=tool,
                    pending_arguments=arguments,
                )

            if result.success:
                had_successful_tool = True
                last_tool_succeeded = True
                safe_result = self._safe_result(result.value)
                context.record_step(tool=tool, arguments=arguments, result=safe_result)
                feedback = {
                    "success": True,
                    "tool": tool,
                    "result": safe_result,
                    "verification": self._safe_result(result.verification),
                }
                self._emit(EventType.TASK_FINISHED, task_id=task.id, step=step_number, tool=tool)
            else:
                last_tool_succeeded = False
                error = result.error or "Falha desconhecida"
                context.record_failure(error)
                feedback = {
                    "success": False,
                    "tool": tool,
                    "error": error,
                    "verification": self._safe_result(result.verification),
                }
                self._emit(EventType.TASK_FAILED, task_id=task.id, step=step_number, tool=tool, error=error)

            messages.append({"role": "assistant", "content": self._safe_json(action)})
            messages.append({"role": "user", "content": "RESULTADO DA FERRAMENTA: " + self._safe_json(feedback)})

        return AutonomousResult(False, "", self.max_steps, executions, f"Limite de {self.max_steps} passos atingido")

    def _initial_prompt(self, context: AgentContext) -> str:
        return (
            f"Objetivo: {context.goal}\n"
            f"Ferramentas disponíveis: {json.dumps(self.schemas.describe(), ensure_ascii=False)}\n"
            "Comece pela ação mínima necessária. Depois de cada resultado, reavalie o objetivo e escolha o próximo passo."
        )

    def _parse_action(self, text: str) -> dict[str, Any]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines and lines[0].strip().startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError("O modelo retornou uma ação que não é JSON válido") from exc
        if not isinstance(payload, dict):
            raise ValueError("Ação do modelo deve ser um objeto JSON")
        action = payload.get("action")
        if action not in {"tool", "finish"}:
            raise ValueError(f"Ação desconhecida: {action}")
        if action == "tool":
            tool = payload.get("tool")
            if not isinstance(tool, str) or not tool.strip():
                raise ValueError("tool deve ser um nome de ferramenta")
            if not isinstance(payload.get("arguments", {}), dict):
                raise ValueError("arguments deve ser um objeto")
        return payload

    @staticmethod
    def _safe_json(value: Any) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            return json.dumps(str(value), ensure_ascii=False)

    @staticmethod
    def _safe_result(value: Any) -> Any:
        try:
            json.dumps(value)
            return value
        except (TypeError, ValueError):
            return str(value)
