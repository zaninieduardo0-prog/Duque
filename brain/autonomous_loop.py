from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable

from core.events import EventType
from core.executor import ExecutionResult, Executor

from .agent_state import AgentContext
from .model import ModelAdapter, extract_json_object
from .self_correction import OPENING_TOOLS
from .tool_schema import ToolSchemaRegistry

MAX_FEEDBACK_CHARS = 8000
MAX_MODEL_ERRORS = 3


@dataclass(slots=True)
class AutonomousResult:
    success: bool
    message: str
    steps: int = 0
    executions: list[ExecutionResult] = field(default_factory=list)
    error: str | None = None
    # Quando a execução parou pedindo confirmação: a ação exata bloqueada e a
    # conversa até ali, para retomar do mesmo ponto em vez de recomeçar.
    pending_action: tuple[str, dict[str, Any]] | None = None
    messages: list[dict[str, str]] = field(default_factory=list)


class AutonomousLoop:
    """Agente limitado: observa, decide, executa, recebe evidência e replaneja."""

    SYSTEM = (
        "Você é o agente operacional do Duque. Trabalhe de forma autônoma e objetiva. "
        "Escolha uma ação por ciclo e use apenas ferramentas disponíveis. "
        "Retorne SOMENTE JSON válido: "
        '{"action":"tool","tool":"nome","arguments":{},"reason":"..."} ou '
        '{"action":"finish","message":"..."}. '
        "Analise cada resultado antes da próxima ação. Para analisar software, inspecione o workspace e o Git, "
        "leia os arquivos relevantes (prefira read_many_files), execute testes e relate os problemas com evidência. "
        "Não altere o código do próprio Duque: isso é feito apenas pela Forja; descreva as mudanças necessárias. "
        "Se algo falhar, escolha outra abordagem. Nunca invente resultados e nunca declare sucesso sem evidência. "
        "Quando a tarefa envolver interface, observe/localize antes de clicar ou digitar. "
        "Não abra o mesmo aplicativo ou site duas vezes e não repita a mesma ferramenta com os mesmos argumentos "
        "quando o estado não mudou. Mensagens finais devem ser curtas e em português do Brasil."
    )

    def __init__(
        self,
        model: ModelAdapter,
        executor: Executor,
        schemas: ToolSchemaRegistry,
        *,
        max_steps: int = 40,
        observer: Callable[[], dict[str, Any]] | None = None,
        event_sink: Callable[..., Any] | None = None,
        system: str | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.sleep = sleep
        self.system = system or self.SYSTEM
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
        resume_messages: list[dict[str, str]] | None = None,
        approved_action: tuple[str, dict[str, Any]] | None = None,
    ) -> AutonomousResult:
        """Executa o objetivo; para retomar após confirmação, passe a conversa
        anterior e a ação exata que o usuário aprovou (só ela é liberada)."""
        task = self.executor.tasks.get(context.task_id)
        if task is None:
            return AutonomousResult(False, "", error="Tarefa do contexto não encontrada")

        messages: list[dict[str, str]] = list(resume_messages) if resume_messages else [
            {"role": "system", "content": self.system},
            {"role": "user", "content": self._initial_prompt(context)},
        ]
        executions: list[ExecutionResult] = []
        had_successful_tool = approved_action is not None
        last_tool_succeeded = True
        finish_rejected = False
        model_errors = 0
        action_counts: Counter[str] = Counter()
        opened: set[str] = set()
        last_action_key: str | None = None
        repeated_action_count = 0
        repeat_limit = 3
        observing = self.observer is not None and self._should_observe(context.goal)

        if approved_action is not None:
            tool, arguments = approved_action
            result = self._execute(task, context, 0, tool, arguments, confirmed=True)
            executions.append(result)
            messages.append({"role": "user", "content": "AÇÃO CONFIRMADA PELO USUÁRIO E EXECUTADA: " + self._feedback(tool, result)})
            last_tool_succeeded = result.success
            if result.success and tool in OPENING_TOOLS:
                opened.add(self._key(tool, arguments))

        for step_number in range(1, self.max_steps + 1):
            if observing:
                try:
                    observation = self.observer() if self.observer else {}
                    context.observe(observation)
                    # Só a observação mais recente importa; as antigas só enchem o contexto.
                    messages = [m for m in messages if not m["content"].startswith("OBSERVAÇÃO ATUAL: ")]
                    messages.append({"role": "user", "content": "OBSERVAÇÃO ATUAL: " + self._truncate(self._safe_json(observation))})
                except Exception as exc:
                    context.record_failure(f"Falha de observação: {type(exc).__name__}: {exc}")

            try:
                response = self.model.respond(messages)
            except Exception as exc:
                model_errors += 1
                error = f"Falha ao consultar o modelo: {type(exc).__name__}: {exc}"
                context.record_failure(error)
                if model_errors >= MAX_MODEL_ERRORS:
                    return AutonomousResult(False, "", step_number, executions, error)
                self.sleep(2 ** model_errors)
                continue
            model_errors = 0

            try:
                action = self._parse_action(response.text)
            except ValueError as exc:
                error = f"Falha ao interpretar decisão do modelo: {exc}"
                context.record_failure(error)
                messages.append({"role": "user", "content": "AÇÃO REJEITADA: " + error + ". Retorne somente um objeto JSON válido no formato solicitado."})
                continue

            if action["action"] == "finish":
                message = str(action.get("message", "Tarefa finalizada.")).strip()
                messages.append({"role": "assistant", "content": self._safe_json(action)})
                if not message:
                    messages.append({"role": "user", "content": "AÇÃO REJEITADA: a mensagem de conclusão está vazia. Continue trabalhando."})
                    continue
                blocked = not had_successful_tool or (not last_tool_succeeded and not finish_rejected)
                if context.goal.strip() and blocked:
                    finish_rejected = True
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
            action_key = self._key(tool, arguments)
            action_counts[action_key] += 1
            if action_key == last_action_key:
                repeated_action_count += 1
            else:
                last_action_key = action_key
                repeated_action_count = 1
            if repeated_action_count > repeat_limit or action_counts[action_key] > repeat_limit * 2:
                error = (
                    f"Loop detectado: a ferramenta {tool} foi solicitada com os mesmos argumentos "
                    f"{action_counts[action_key]} vezes sem mudança de estado."
                )
                context.record_failure(error)
                return AutonomousResult(False, "", step_number, executions, error)

            messages.append({"role": "assistant", "content": self._safe_json(action)})
            if tool in OPENING_TOOLS and action_key in opened:
                # Abrir de novo só empilharia janelas iguais.
                messages.append({"role": "user", "content": "RESULTADO DA FERRAMENTA: " + self._safe_json({"success": True, "tool": tool, "note": "já foi aberto nesta tarefa; não abra de novo"})})
                continue

            validation = self.schemas.validate(tool, arguments)
            if not validation.valid:
                error = validation.error or "Ação inválida"
                context.record_failure(error)
                messages.append({"role": "user", "content": f"AÇÃO REJEITADA: {error}. Escolha uma ferramenta válida e tente novamente."})
                continue

            result = self._execute(task, context, step_number, tool, arguments, confirmed=False)
            executions.append(result)
            if result.confirmation_required:
                return AutonomousResult(
                    False,
                    "",
                    step_number,
                    executions,
                    result.error,
                    pending_action=(tool, arguments),
                    messages=messages,
                )
            if result.success:
                had_successful_tool = True
                last_tool_succeeded = True
                finish_rejected = False
                if tool in OPENING_TOOLS:
                    opened.add(action_key)
            else:
                last_tool_succeeded = False
            messages.append({"role": "user", "content": "RESULTADO DA FERRAMENTA: " + self._feedback(tool, result)})

        return AutonomousResult(False, "", self.max_steps, executions, f"Limite de {self.max_steps} passos atingido")

    def _execute(self, task: Any, context: AgentContext, step: int, tool: str, arguments: dict[str, Any], *, confirmed: bool) -> ExecutionResult:
        self._emit(EventType.TASK_STARTED, task_id=task.id, step=step, tool=tool)
        result = self.executor.execute_step(task, tool, arguments, confirmed=confirmed, manage_task=False)
        if result.confirmation_required:
            return result
        if result.success:
            context.record_step(tool=tool, arguments=arguments, result=self._safe_result(result.value))
            self._emit(EventType.TASK_FINISHED, task_id=task.id, step=step, tool=tool)
        else:
            context.record_failure(result.error or "Falha desconhecida")
            self._emit(EventType.TASK_FAILED, task_id=task.id, step=step, tool=tool, error=result.error or "Falha desconhecida")
        return result

    def _feedback(self, tool: str, result: ExecutionResult) -> str:
        if result.success:
            feedback = {"success": True, "tool": tool, "result": self._safe_result(result.value)}
        else:
            feedback = {"success": False, "tool": tool, "error": result.error or "Falha desconhecida"}
        if result.verification is not None:
            feedback["verification"] = self._safe_result(result.verification)
        return self._truncate(self._safe_json(feedback))

    @staticmethod
    def _truncate(text: str) -> str:
        if len(text) <= MAX_FEEDBACK_CHARS:
            return text
        return text[:MAX_FEEDBACK_CHARS] + "...[truncado]"

    def _key(self, tool: str, arguments: dict[str, Any]) -> str:
        return self._safe_json({"tool": tool, "arguments": arguments})

    @staticmethod
    def _should_observe(goal: str) -> bool:
        """Observação de tela só é necessária quando a tarefa depende da interface gráfica."""
        normalized = " ".join(goal.casefold().split())
        markers = (
            "tela", "interface", "janela", "clique", "clicar", "digite",
            "navegador", "chrome", "edge", "firefox", "whatsapp", "instagram",
            "spotify", "youtube", "aplicativo", "app", "site",
        )
        return any(marker in normalized for marker in markers)

    def _initial_prompt(self, context: AgentContext) -> str:
        return (
            f"Objetivo: {context.goal}\n"
            f"Ferramentas disponíveis: {json.dumps(self.schemas.describe(), ensure_ascii=False)}\n"
            "Comece pela ação mínima necessária. Depois de cada resultado, reavalie o objetivo e escolha o próximo passo."
        )

    def _parse_action(self, text: str) -> dict[str, Any]:
        payload = extract_json_object(text)
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
            return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)
        except Exception:
            return json.dumps(str(value), ensure_ascii=False)

    @staticmethod
    def _safe_result(value: Any) -> Any:
        try:
            json.dumps(value)
            return value
        except (TypeError, ValueError):
            return str(value)
