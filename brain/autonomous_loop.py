from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable

from core.events import EventType
from core.executor import Executor, ExecutionResult
from .agent_state import AgentContext
from .model import ModelAdapter, extract_json_object
from .tool_schema import ToolSchemaRegistry

# Ferramentas que abrem algo na tela: abrir de novo na mesma tarefa só empilha janelas.
OPENING_TOOLS = frozenset({"open_app", "open_url", "open_path", "open_folder", "open_search_result", "google_search", "whatsapp_web_open"})
MAX_FEEDBACK_CHARS = 6000  # resultado de ferramenta enviado ao modelo (read_many_files pode ter MBs)
MAX_HISTORY = 60  # mensagens da conversa com o modelo, além do sistema e do objetivo
MAX_MODEL_ERRORS = 3  # falhas seguidas do próprio modelo (rede, cota) antes de desistir
MAX_FINISH_REJECTIONS = 3


@dataclass(slots=True)
class AutonomousResult:
    success: bool
    message: str
    steps: int = 0
    executions: list[ExecutionResult] = field(default_factory=list)
    error: str | None = None
    # Quando parou pedindo confirmação: a ação exata bloqueada e a conversa até ali,
    # para retomar do mesmo ponto (e liberar só essa ação) em vez de recomeçar do zero.
    pending_action: tuple[str, dict[str, Any]] | None = None
    messages: list[dict[str, str]] = field(default_factory=list)


class AutonomousLoop:
    """Agente limitado: observa, decide, executa, recebe evidência e replaneja."""

    SYSTEM = (
        "Você é o agente operacional e desenvolvedor do Duque. Trabalhe de forma autônoma e objetiva. "
        "Escolha uma ação por ciclo e use apenas ferramentas disponíveis. "
        "Retorne SOMENTE JSON válido: "
        '{"action":"tool","tool":"nome","arguments":{},"reason":"..."} ou '
        '{"action":"finish","message":"..."}. '
        "Analise todos os resultados antes da próxima ação. Para desenvolvimento de software, inspecione o workspace e o Git, leia os arquivos relevantes, execute testes e relate os problemas com evidência. "
        "Para alterar o código do próprio Duque, use forge_improve com um objetivo claro: a Forja trabalha numa cópia isolada, testa e aplica com segurança. Não edite nem faça commit do código em execução. "
        "Se algo falhar, corrija ou escolha outra abordagem. Nunca invente resultados e nunca declare sucesso sem evidência. "
        "Quando a tarefa envolver interface, prefira observar/localizar antes de clicar ou digitar. "
        "Não abra o mesmo aplicativo ou site duas vezes. "
        "Evite repetir a mesma ferramenta com os mesmos argumentos quando o estado não mudou. Para ler código, prefira read_many_files em vez de várias leituras isoladas. Em tarefas de desenvolvimento, mantenha foco no objetivo, faça progresso verificável e não fique rechecando o mesmo estado indefinidamente. Só finalize depois que os resultados das ferramentas fornecerem evidência suficiente de conclusão."
    )

    def __init__(
        self,
        model: ModelAdapter,
        executor: Executor,
        schemas: ToolSchemaRegistry,
        *,
        max_steps: int = 160,
        observer: Callable[[], dict[str, Any]] | None = None,
        event_sink: Callable[..., Any] | None = None,
        system: str | None = None,
        time_limit: float | None = None,
        blocked_tools: frozenset[str] | set[str] = frozenset(),
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.system = system or self.SYSTEM
        self.time_limit = time_limit
        self.model = model
        self.executor = executor
        self.schemas = schemas
        self.max_steps = max(1, max_steps)
        # Modelos pequenos (locais) às vezes não acertam o formato: desiste cedo em vez de
        # gastar minutos de passos inúteis.
        self.invalid_limit = 5
        self.observer = observer
        self.event_sink = event_sink
        # Ferramentas proibidas neste laço (ex.: escrever no repositório do próprio TELEX em execução).
        self.blocked_tools = frozenset(blocked_tools)
        self.sleep = sleep

    def _emit(self, event: EventType, **data: Any) -> None:
        if self.event_sink:
            self.event_sink(event, **data)

    def run(
        self,
        context: AgentContext,
        *,
        confirmed: bool = False,
        approved_action: tuple[str, dict[str, Any]] | None = None,
        resume_messages: list[dict[str, str]] | None = None,
    ) -> AutonomousResult:
        """Executa o objetivo.

        ``confirmed=True`` libera todas as ações de risco (só para ambientes isolados,
        como a cópia da Forja). Para retomar depois que o Du confirmou, passe a ação
        exata que ele aprovou (``approved_action``) e a conversa anterior
        (``resume_messages``): só aquela ação é liberada e nada é refeito.
        """
        task = self.executor.tasks.get(context.task_id)
        if task is None:
            return AutonomousResult(False, "", error="Tarefa do contexto não encontrada")

        messages: list[dict[str, str]] = list(resume_messages) if resume_messages else [
            {"role": "system", "content": self.system},
            {"role": "user", "content": self._initial_prompt(context)},
        ]
        executions: list[ExecutionResult] = []
        had_successful_tool = False
        last_tool_succeeded = False
        last_action_key: str | None = None
        repeated_action_count = 0
        repeat_limit = 3
        action_counts: Counter[str] = Counter()
        opened: set[str] = set()
        invalid_streak = 0  # respostas do modelo recusadas em sequência
        model_errors = 0
        finish_rejections = 0
        observing = self.observer is not None and self._should_observe(context.goal)

        started = time.monotonic()

        if approved_action is not None:
            tool, arguments = approved_action
            result = self._execute(task, context, 0, tool, arguments, confirmed=True, reason="confirmado pelo Du")
            executions.append(result)
            messages.append({"role": "user", "content": "AÇÃO CONFIRMADA PELO USUÁRIO E EXECUTADA: " + self._feedback(tool, result)})
            had_successful_tool = last_tool_succeeded = result.success
            if result.success and tool in OPENING_TOOLS:
                opened.add(self._key(tool, arguments))

        for step_number in range(1, self.max_steps + 1):
            if self.time_limit is not None and time.monotonic() - started > self.time_limit:
                return AutonomousResult(
                    False, f"Parei: passou do tempo limite de {int(self.time_limit // 60)} min sem concluir.",
                    step_number - 1, executions, "tempo limite",
                )
            if observing and self.observer is not None:
                try:
                    observation = self.observer()
                    context.observe(observation)
                    # Só a observação mais recente importa; as antigas só enchem o contexto.
                    messages = [m for m in messages if not m["content"].startswith("OBSERVAÇÃO ATUAL: ")]
                    messages.append({"role": "user", "content": "OBSERVAÇÃO ATUAL: " + self._truncate(self._safe_json(observation))})
                except Exception as exc:
                    context.record_failure(f"Falha de observação: {type(exc).__name__}: {exc}")
            messages = self._trim(messages)

            try:
                response = self.model.respond(messages)
            except Exception as exc:
                # Falha do próprio modelo (rede, cota, timeout): não é culpa do formato;
                # espera um pouco e desiste depois de poucas tentativas.
                model_errors += 1
                error = f"Falha ao consultar o modelo: {type(exc).__name__}: {exc}"
                context.record_failure(error)
                if model_errors >= MAX_MODEL_ERRORS:
                    return self._gave_up(task.id, step_number, executions, "o modelo não respondeu (sem rede, sem crédito ou fora do ar)")
                self.sleep(min(8.0, 2.0 ** (model_errors - 1)))
                continue
            model_errors = 0

            try:
                action = self._parse_action(response.text)
            except Exception as exc:
                error = f"Falha ao interpretar decisão do modelo: {type(exc).__name__}: {exc}"
                context.record_failure(error)
                invalid_streak += 1
                if invalid_streak >= self.invalid_limit:
                    return self._gave_up(task.id, step_number, executions, "o modelo não conseguiu responder no formato esperado")
                messages.append({"role": "user", "content": "AÇÃO REJEITADA: " + error + ". Retorne somente um objeto JSON válido no formato solicitado."})
                continue
            invalid_streak = 0

            if action["action"] == "cannot":
                # Avaliou que não consegue: resposta honesta, sem fingir sucesso.
                message = str(action.get("message", "")).strip() or "Não consigo fazer isso com o que tenho."
                self._emit(EventType.TASK_FAILED, task_id=task.id, step=step_number, error=message)
                return AutonomousResult(False, message, step_number - 1, executions, "não é possível")
            if action["action"] == "finish":
                message = str(action.get("message", "Tarefa finalizada.")).strip()
                messages.append({"role": "assistant", "content": self._safe_json(action)})
                if not message:
                    messages.append({"role": "user", "content": "AÇÃO REJEITADA: a mensagem de conclusão está vazia. Continue trabalhando."})
                    continue
                if context.goal.strip() and (not had_successful_tool or not last_tool_succeeded):
                    finish_rejections += 1
                    if finish_rejections >= MAX_FINISH_REJECTIONS:
                        # Insiste em concluir sem evidência: para em vez de girar até o limite de passos.
                        self._emit(EventType.TASK_FAILED, task_id=task.id, step=step_number, error="conclusão sem evidência")
                        return AutonomousResult(False, f"Não consegui comprovar que terminei: {message}", step_number - 1, executions, "conclusão sem evidência")
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
                # Também pega laços alternados (A, B, A, B...), não só repetições seguidas.
                error = (
                    f"Loop detectado: a ferramenta {tool} foi solicitada com os mesmos argumentos "
                    f"{max(repeated_action_count, action_counts[action_key])} vezes sem mudança de estado."
                )
                context.record_failure(error)
                return AutonomousResult(False, "", step_number, executions, error)

            messages.append({"role": "assistant", "content": self._safe_json(action)})
            if tool in OPENING_TOOLS and action_key in opened:
                messages.append({"role": "user", "content": "RESULTADO DA FERRAMENTA: " + self._safe_json(
                    {"success": True, "tool": tool, "note": "já foi aberto nesta tarefa; não abra de novo, use a janela que já está aberta"}
                )})
                continue
            if tool in self.blocked_tools:
                validation_error: str | None = (
                    f"a ferramenta {tool} não pode ser usada aqui (alteraria o TELEX em execução); "
                    "para mudar o código do TELEX use forge_improve"
                )
            else:
                validation = self.schemas.validate(tool, arguments)
                validation_error = None if validation.valid else (validation.error or "Ação inválida")
            if validation_error is not None:
                context.record_failure(validation_error)
                invalid_streak += 1
                if invalid_streak >= self.invalid_limit:
                    return self._gave_up(task.id, step_number, executions, "o modelo insistiu em ações inválidas")
                messages.append({"role": "user", "content": f"AÇÃO REJEITADA: {validation_error}. Escolha uma ferramenta válida e tente novamente."})
                continue
            invalid_streak = 0

            result = self._execute(task, context, step_number, tool, arguments, confirmed=confirmed, reason=str(action.get("reason", ""))[:200])
            executions.append(result)
            if result.confirmation_required:
                return AutonomousResult(
                    False, "Preciso da sua confirmação antes de executar essa ação.", step_number, executions, result.error,
                    pending_action=(tool, dict(arguments)), messages=messages,
                )
            if result.success:
                had_successful_tool = True
                last_tool_succeeded = True
                finish_rejections = 0
                if tool in OPENING_TOOLS:
                    opened.add(action_key)
            else:
                last_tool_succeeded = False
            messages.append({"role": "user", "content": "RESULTADO DA FERRAMENTA: " + self._feedback(tool, result)})

        return AutonomousResult(False, "", self.max_steps, executions, f"Limite de {self.max_steps} passos atingido")

    def _execute(self, task: Any, context: AgentContext, step: int, tool: str, arguments: dict[str, Any], *, confirmed: bool, reason: str = "") -> ExecutionResult:
        self._emit(
            EventType.TASK_STARTED, task_id=task.id, step=step, tool=tool,
            arguments=arguments if isinstance(arguments, dict) else {}, reason=reason,
        )
        result = self.executor.execute_step(task, tool, arguments, confirmed=confirmed, manage_task=False)
        if result.confirmation_required:
            return result
        if result.success:
            context.record_step(tool=tool, arguments=arguments, result=self._safe_result(result.value))
            self._emit(EventType.TASK_FINISHED, task_id=task.id, step=step, tool=tool)
        else:
            error = result.error or "Falha desconhecida"
            context.record_failure(error)
            self._emit(EventType.TASK_FAILED, task_id=task.id, step=step, tool=tool, error=error)
        return result

    def _feedback(self, tool: str, result: ExecutionResult) -> str:
        feedback: dict[str, Any]
        if result.success:
            feedback = {"success": True, "tool": tool, "result": self._safe_result(result.value)}
        else:
            feedback = {"success": False, "tool": tool, "error": result.error or "Falha desconhecida"}
        feedback["verification"] = self._safe_result(result.verification)
        return self._truncate(self._safe_json(feedback))

    @staticmethod
    def _truncate(text: str) -> str:
        if len(text) <= MAX_FEEDBACK_CHARS:
            return text
        return text[:MAX_FEEDBACK_CHARS] + "...[truncado]"

    @staticmethod
    def _trim(messages: list[dict[str, str]]) -> list[dict[str, str]]:
        """Mantém sistema + objetivo + as últimas mensagens: o contexto não cresce sem limite."""
        if len(messages) <= MAX_HISTORY + 2:
            return messages
        return messages[:2] + messages[-MAX_HISTORY:]

    def _key(self, tool: str, arguments: Any) -> str:
        return self._safe_json({"tool": tool, "arguments": arguments})

    def _gave_up(self, task_id: str, step_number: int, executions: list[ExecutionResult], why: str) -> AutonomousResult:
        message = f"Não consegui levar isso adiante: {why}."
        self._emit(EventType.TASK_FAILED, task_id=task_id, step=step_number, error=message)
        return AutonomousResult(False, message, step_number, executions, why)

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
            f"Ferramentas disponíveis: {json.dumps([spec for spec in self.schemas.describe() if spec.get('name') not in self.blocked_tools], ensure_ascii=False)}\n"
            "Comece pela ação mínima necessária. Depois de cada resultado, reavalie o objetivo e escolha o próximo passo."
        )

    def _parse_action(self, text: str) -> dict[str, Any]:
        payload = extract_json_object(text)  # aceita ```json e JSON no meio de texto (modelo pequeno)
        if payload is None:
            raise ValueError("O modelo retornou uma ação que não é JSON válido")
        if not isinstance(payload, dict):
            raise ValueError("Ação do modelo deve ser um objeto JSON")
        action = payload.get("action")
        if action not in {"tool", "finish", "cannot"}:
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
