from __future__ import annotations

import json
import os
import re
import threading
from collections import deque
from dataclasses import dataclass, field
from time import time
from typing import Any
from uuid import uuid4

from automation.runner import ScheduledTaskRunner
from automation.scheduler import Scheduler
from computer.code_tools import CodeTools
from computer.runtime import create_ui_tools, create_verification
from computer.screen_tools import ScreenTools
from computer.system_tools import SystemTools
from computer.tools import ComputerTools
from computer.ui_tools import UITools
from computer.verification_tools import VerificationTools
from computer.verified_ui import VerifiedScreenActions
from computer.workspace import Workspace
from core.engine import DuqueEngine
from core.events import EventType
from core.executor import ExecutionResult, Executor
from core.task_engine import TaskEngine
from core.tasks import Task, TaskManager, TaskStatus
from memory.memory import Memory, MemoryLayer

from .agent_state import AgentContext
from .autonomous_loop import AutonomousLoop
from .model import ModelAdapter, NullModel, OpenAIResponsesModel
from .model_planner import ModelPlanner
from .planner import Planner, StepKind
from .router import DETERMINISTIC_INTENTS, IntentRouter
from .self_correction import SelfCorrection
from .self_development import SelfDevelopment
from .tool_schema import ToolSchemaRegistry, ToolSpec

# Uma confirmação esquecida não pode ser aprovada por um "sim" horas depois.
CONFIRMATION_TTL_SECONDS = 300.0
# "ele está aberto?" só se refere ao último app por um tempo curto.
LAST_APP_TTL_SECONDS = 600.0
HISTORY_TURNS = 10
MIN_REPEAT_SECONDS = 60.0
OFFLINE_MESSAGE = (
    "Estou sem acesso ao modelo (OPENAI_API_KEY não configurada). "
    "Consigo apenas comandos diretos, como 'abra o chrome' ou 'pesquise o clima'."
)

_CONFIRM_EXACT = {"sim", "confirmo", "confirmado", "confirmar", "pode fazer", "pode executar", "pode", "autorizo", "autorizado", "ok", "pode sim"}
_CONFIRM_PREFIX = ("sim ", "confirmo ", "pode fazer", "pode executar", "autorizo ")
_CANCEL_EXACT = {"não", "nao", "n", "cancela", "cancelar", "deixa", "deixa pra lá", "deixa pra la", "não pode", "nao pode"}
_CANCEL_PREFIX = ("não ", "nao ", "cancela ", "cancelar ")


def _words(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.casefold()).split())


@dataclass(slots=True)
class AgentResult:
    text: str
    task_id: str | None = None
    execution: ExecutionResult | None = None
    attempts: int = 1
    awaiting_confirmation: bool = False


@dataclass(slots=True)
class PendingConfirmation:
    task_id: str
    text: str
    intent: str
    # Etapas restantes a partir da que pediu confirmação (fluxo planejado).
    steps: list[tuple[str, dict[str, Any]]]
    created_at: float = field(default_factory=time)
    # Fluxo autônomo: a ação exata bloqueada e a conversa para retomar dali.
    action: tuple[str, dict[str, Any]] | None = None
    messages: list[dict[str, str]] = field(default_factory=list)

    def expired(self) -> bool:
        return time() - self.created_at > CONFIRMATION_TTL_SECONDS


class AgentLoop:
    """Orquestra entendimento, planejamento, execução, verificação, correção, memória e agenda."""

    def __init__(self, engine: DuqueEngine | None = None, tasks: TaskManager | None = None, executor: Executor | None = None, workspace: Workspace | None = None, ui_tools: UITools | None = None, model: ModelAdapter | None = None, model_planner: ModelPlanner | None = None, memory: Memory | None = None) -> None:
        self.engine = engine or DuqueEngine()
        self.router = IntentRouter()
        self.planner = Planner()
        self.tasks = tasks or TaskManager()
        self.verification = create_verification()
        self.executor = executor or Executor(self.tasks, verification=self.verification, event_sink=self.engine.emit)
        self.workspace = workspace or Workspace(os.getenv("DUQUE_WORKSPACE_ROOT", "."))
        ComputerTools().register(self.executor)
        code_tools = CodeTools(self.workspace)
        code_tools.register(self.executor)
        SystemTools().register(self.executor)
        SelfDevelopment(self.workspace, code_tools).register(self.executor)
        active_ui_tools = ui_tools or create_ui_tools()
        active_ui_tools.register(self.executor)
        if self.verification is not None:
            VerificationTools(self.verification).register(self.executor)
            ScreenTools(self.verification).register(self.executor)
            VerifiedScreenActions(active_ui_tools.controller, self.verification).register(self.executor)
        self.task_engine = TaskEngine(self.executor, self.tasks, self.engine.emit)
        self.correction = SelfCorrection(self.task_engine)
        self.model = model or self._create_default_model()
        self.schemas = ToolSchemaRegistry()
        self.memory = memory or Memory(self.tasks.database)
        self._lock = threading.RLock()
        self._history: deque[dict[str, str]] = deque(maxlen=HISTORY_TURNS * 2)
        self._pending_confirmation: PendingConfirmation | None = None
        self._last_app: str | None = None
        self._last_app_at = 0.0

        self.scheduler = Scheduler(database=self.tasks.database)
        self.scheduled_runner = ScheduledTaskRunner(self.scheduler, self.task_engine, self.tasks, event_sink=self.engine.emit, lock=self._lock)
        self.executor.register("schedule_task", self._schedule_task)
        self.executor.register("schedule_reminder", self._schedule_reminder)
        self.executor.register("list_scheduled_jobs", self._list_scheduled_jobs)
        self.executor.register("cancel_scheduled_job", self._cancel_scheduled_job)
        self._register_tool_schemas()
        self.model_planner = model_planner or ModelPlanner(self.model, self.schemas)
        self.autonomous = AutonomousLoop(self.model, self.executor, self.schemas, observer=self._observe_screen, event_sink=self.engine.emit)
        self._restore_pending_confirmation()

    def start_background(self) -> None:
        """Liga a agenda. Fica fora do construtor para que nada rode antes de o
        servidor estar pronto e inscrito nos eventos."""
        self.scheduled_runner.start()

    @property
    def awaiting_confirmation(self) -> bool:
        return self._pending_confirmation is not None

    def _observe_screen(self) -> dict[str, object]:
        if self.verification is None:
            return {}
        observation = self.verification.snapshot()
        return {
            "width": observation.width,
            "height": observation.height,
            "source": observation.source,
            "description": observation.description or {},
        }

    def _register_tool_schemas(self) -> None:
        # git_commit/git_pull/git_push não são oferecidos ao modelo: mexer no
        # repositório do Duque em execução é trabalho da Forja.
        specs = [
            ToolSpec("open_app", "Abre um aplicativo conhecido pelo nome", ("name",), {"name": str}),
            ToolSpec("close_app", "Fecha um aplicativo pelo processo conhecido", ("name",), {"name": str}),
            ToolSpec("is_app_running", "Verifica se um aplicativo está em execução", ("name",), {"name": str}),
            ToolSpec("open_url", "Abre uma URL no navegador; pode ser usada para serviços web como WhatsApp Web", ("url",), {"url": str}),
            ToolSpec("open_path", "Abre uma pasta ou documento existente (não executa programas)", ("path",), {"path": str}),
            ToolSpec("web_search", "Pesquisa na web sem abrir o navegador", ("query",), {"query": str}),
            ToolSpec("open_search_result", "Abre no navegador um resultado da pesquisa recente", (), {"index": int}),
            ToolSpec("read_file", "Lê um arquivo do workspace", ("path",), {"path": str}),
            ToolSpec("read_many_files", "Lê vários arquivos do workspace", ("paths",), {"paths": list}),
            ToolSpec("write_file", "Escreve arquivo no workspace", ("path", "content"), {"path": str, "content": str}),
            ToolSpec("delete_file", "Exclui um arquivo do workspace", ("path",), {"path": str}),
            ToolSpec("list_files", "Lista arquivos do workspace"),
            ToolSpec("inspect_workspace", "Inspeciona a estrutura do workspace"),
            ToolSpec("run_tests", "Executa a suíte de testes do workspace", (), {"path": str}),
            ToolSpec("run_python", "Executa um script Python do workspace", ("path",), {"path": str}),
            ToolSpec("git_status", "Consulta o estado do repositório Git sem alterar arquivos"),
            ToolSpec("git_diff", "Consulta diferenças locais do repositório Git", (), {"path": str}),
            ToolSpec("git_log", "Consulta o histórico recente do Git", (), {"limit": int}),
            ToolSpec("git_fetch", "Atualiza referências remotas do Git sem alterar o working tree"),
            ToolSpec("ui_click", "Clica na tela", ("x", "y"), {"x": int, "y": int}),
            ToolSpec("ui_type_text", "Digita texto", ("text",), {"text": str}),
            ToolSpec("ui_press", "Pressiona uma tecla", ("key",), {"key": str}),
            ToolSpec("ui_hotkey", "Pressiona combinação de teclas", ("keys",), {"keys": list}),
            ToolSpec("screenshot", "Captura a tela"),
            ToolSpec("screen_snapshot", "Observa a tela com contexto semântico"),
            ToolSpec("screen_find", "Localiza um elemento visual por texto", ("text",), {"text": str}),
            ToolSpec("screen_click_text", "Localiza um texto na tela e clica no elemento; pode confirmar texto esperado", ("text",), {"text": str, "expected_text": str, "expected_not_text": str}),
            ToolSpec("screen_contains_text", "Verifica se um texto está visível na tela (OCR/visão)", ("text",), {"text": str}),
            ToolSpec("schedule_task", "Agenda ferramentas para rodar depois (repetição mínima de 60 s; ações que exigem confirmação não podem ser agendadas)", ("description", "delay_seconds", "steps"), {"description": str, "delay_seconds": (int, float), "steps": list, "repeat_seconds": (int, float)}),
            ToolSpec("schedule_reminder", "Cria um lembrete que o Duque avisa depois (repetição mínima de 60 s)", ("message", "delay_seconds"), {"message": str, "delay_seconds": (int, float), "repeat_seconds": (int, float)}),
            ToolSpec("list_scheduled_jobs", "Lista lembretes e tarefas agendadas ativos"),
            ToolSpec("cancel_scheduled_job", "Cancela um lembrete ou tarefa agendada pelo id", ("job_id",), {"job_id": str}),
            ToolSpec("system_info", "Obtém informações do sistema local"),
            ToolSpec("environment", "Lê uma variável de ambiente (segredos são ocultados)", (), {"name": str}),
            ToolSpec("list_directory", "Lista qualquer diretório local", (), {"path": str}),
            ToolSpec("read_any_file", "Lê qualquer arquivo local", ("path",), {"path": str, "max_bytes": int}),
            ToolSpec("write_any_file", "Escreve qualquer arquivo local", ("path", "content"), {"path": str, "content": str}),
            ToolSpec("delete_any_file", "Exclui arquivo ou diretório local", ("path",), {"path": str}),
            ToolSpec("copy_path", "Copia arquivo ou diretório local", ("source", "destination"), {"source": str, "destination": str}),
            ToolSpec("move_path", "Move arquivo ou diretório local", ("source", "destination"), {"source": str, "destination": str}),
            ToolSpec("run_command", "Executa um comando do sistema local", ("command",), {"command": str, "timeout": int}),
            ToolSpec("list_processes", "Lista processos em execução"),
            ToolSpec("kill_process", "Encerra um processo local", ("pid",), {"pid": int, "force": bool}),
        ]
        registered = set(self.executor.tools.names())
        for spec in specs:
            if spec.name in registered:
                self.schemas.register(spec)

    # ----------------------------------------------------------------- agenda

    @staticmethod
    def _repeat(repeat_seconds: int | float | None) -> float | None:
        if repeat_seconds is None:
            return None
        repeat = float(repeat_seconds)
        if repeat < MIN_REPEAT_SECONDS:
            raise ValueError(f"repeat_seconds deve ser de pelo menos {int(MIN_REPEAT_SECONDS)} segundos")
        return repeat

    def _schedule_task(self, description: str, delay_seconds: int | float, steps: list[dict[str, object]], repeat_seconds: int | float | None = None) -> dict[str, object]:
        if not isinstance(description, str) or not description.strip():
            raise ValueError("description não pode ser vazio")
        if not isinstance(steps, list) or not steps:
            raise ValueError("steps deve conter pelo menos uma etapa")
        repeat = self._repeat(repeat_seconds)
        normalized: list[dict[str, object]] = []
        for item in steps:
            if not isinstance(item, dict):
                raise ValueError("Cada etapa deve ser um objeto")
            tool = item.get("tool")
            arguments = item.get("arguments", {})
            if not isinstance(tool, str) or not tool.strip():
                raise ValueError("Cada etapa precisa de uma ferramenta")
            if not isinstance(arguments, dict):
                raise ValueError("arguments deve ser um objeto")
            if tool.startswith(("schedule_", "cancel_scheduled")):
                raise ValueError("Uma tarefa agendada não pode agendar outras tarefas")
            if self.executor.security.assess(tool).confirmation_required:
                # Ninguém estará presente para confirmar quando o job rodar.
                raise ValueError(f"A ação '{tool}' exige confirmação e não pode ser agendada")
            validation = self.schemas.validate(tool, arguments)
            if not validation.valid:
                raise ValueError(validation.error or f"Etapa inválida: {tool}")
            normalized.append({"tool": tool, "arguments": arguments})
        job = self.scheduler.add_task_after(description, max(0.0, float(delay_seconds)), steps=normalized, repeat_seconds=repeat)
        return {"job_id": job.id, "description": description, "run_at": job.run_at, "scheduled": True}

    def _schedule_reminder(self, message: str, delay_seconds: int | float, repeat_seconds: int | float | None = None) -> dict[str, object]:
        if not isinstance(message, str) or not message.strip():
            raise ValueError("message não pode ser vazio")
        repeat = self._repeat(repeat_seconds)
        job = self.scheduler.add_after(message.strip(), max(0.0, float(delay_seconds)), repeat_seconds=repeat, kind="reminder")
        return {"job_id": job.id, "description": job.description, "run_at": job.run_at, "scheduled": True}

    def _list_scheduled_jobs(self) -> dict[str, object]:
        jobs = [
            {"job_id": job.id, "description": job.description, "run_at": job.run_at, "repeat_seconds": job.repeat_seconds}
            for job in self.scheduler.list()
        ]
        return {"jobs": jobs, "count": len(jobs)}

    def _cancel_scheduled_job(self, job_id: str) -> dict[str, object]:
        if not self.scheduler.cancel(job_id):
            raise ValueError(f"Agendamento não encontrado: {job_id}")
        return {"job_id": job_id, "cancelled": True}

    # ----------------------------------------------------------------- modelo

    @staticmethod
    def _create_default_model() -> ModelAdapter:
        """Usa o modelo da API quando a chave estiver configurada; caso contrário, permanece offline."""
        if os.getenv("OPENAI_API_KEY"):
            try:
                return OpenAIResponsesModel()
            except RuntimeError:
                pass
        return NullModel()

    @property
    def online(self) -> bool:
        return not isinstance(self.model, NullModel)

    def _chat_response(self, text: str) -> str:
        if not self.online:
            return OFFLINE_MESSAGE
        response = self.model.respond([
            {
                "role": "system",
                "content": (
                    "Você é o Duque, assistente pessoal do usuário (chame-o de Du). "
                    "Responda em português do Brasil, de forma natural, direta e útil. "
                    "Não diga que é um modelo de linguagem."
                ),
            },
            *self._history,
            {"role": "user", "content": text},
        ])
        return response.text.strip() or "Não consegui formular uma resposta agora."

    def _summarize(self, text: str, value: object) -> str:
        """Resume para o usuário um resultado de ferramenta sem formato conhecido."""
        payload = json.dumps(value, ensure_ascii=False, default=str)
        if not self.online:
            return payload[:1500] + ("..." if len(payload) > 1500 else "")
        try:
            response = self.model.respond([
                {"role": "system", "content": "Resuma para o usuário, em português do Brasil e em poucas frases, o resultado abaixo. Não invente dados."},
                {"role": "user", "content": f"Pedido: {text}\nResultado: {payload[:6000]}"},
            ])
            return response.text.strip() or "Tarefa concluída."
        except Exception:
            return payload[:1500]

    # ----------------------------------------------------------- confirmação

    @staticmethod
    def _is_confirmation(text: str) -> bool:
        value = _words(text)
        return value in _CONFIRM_EXACT or value.startswith(_CONFIRM_PREFIX)

    @staticmethod
    def _is_cancellation(text: str) -> bool:
        value = _words(text)
        return value in _CANCEL_EXACT or value.startswith(_CANCEL_PREFIX)

    @staticmethod
    def _describe_steps(steps: list[tuple[str, dict[str, Any]]]) -> str:
        parts = []
        for tool, arguments in steps:
            args = json.dumps(arguments, ensure_ascii=False, default=str)
            parts.append(f"{tool} {args[:200]}")
        return "; ".join(parts)

    def _confirmation_prompt(self, steps: list[tuple[str, dict[str, Any]]]) -> str:
        risky = [step for step in steps if self.executor.security.assess(step[0]).confirmation_required] or steps[:1]
        return f"Preciso da sua confirmação para: {self._describe_steps(risky)}. Responda 'confirmo' ou 'cancela'."

    def _cancel_pending(self, reason: str) -> PendingConfirmation | None:
        pending = self._pending_confirmation
        self._pending_confirmation = None
        if pending is None:
            return None
        task = self.tasks.get(pending.task_id)
        if task is not None and task.status in {TaskStatus.AWAITING_CONFIRMATION, TaskStatus.RUNNING, TaskStatus.PENDING}:
            self.tasks.cancel(task.id)
        self.memory.remember(MemoryLayer.OPERATIONAL, f"task:{pending.task_id}", {"description": pending.text, "status": "cancelled", "reason": reason})
        return pending

    def _restore_pending_confirmation(self) -> None:
        """Recupera no máximo uma confirmação recente; as demais são canceladas."""
        candidates: list[Task] = []
        for task in self.tasks.list(TaskStatus.AWAITING_CONFIRMATION):
            metadata = task.metadata
            requested_at = metadata.get("confirmation_requested_at")
            fresh = isinstance(requested_at, (int, float)) and time() - requested_at <= CONFIRMATION_TTL_SECONDS
            restorable = (
                fresh
                and metadata.get("source") not in {"scheduler", "scheduled"}
                and metadata.get("confirmation_intent") not in {None, "autonomous"}
                and isinstance(metadata.get("confirmation_steps"), list)
            )
            if restorable:
                candidates.append(task)
            else:
                # Autônomas não sobrevivem ao reinício (a conversa com o modelo se perdeu).
                self.tasks.cancel(task.id)
        if not candidates:
            return
        task = max(candidates, key=lambda item: item.created_at)
        for other in candidates:
            if other.id != task.id:
                self.tasks.cancel(other.id)
        steps: list[tuple[str, dict[str, Any]]] = []
        for item in task.metadata["confirmation_steps"]:
            if not isinstance(item, dict) or not isinstance(item.get("tool"), str) or not isinstance(item.get("arguments", {}), dict):
                self.tasks.cancel(task.id)
                return
            steps.append((item["tool"], item.get("arguments", {})))
        self._pending_confirmation = PendingConfirmation(
            task.id, task.description, str(task.metadata["confirmation_intent"]), steps,
            created_at=float(task.metadata["confirmation_requested_at"]),
        )

    def _await_confirmation(self, task: Task, text: str, intent: str, steps: list[tuple[str, dict[str, Any]]], *, action: tuple[str, dict[str, Any]] | None = None, messages: list[dict[str, str]] | None = None) -> str:
        prompt = self._confirmation_prompt(steps)
        if task.status == TaskStatus.RUNNING:
            self.tasks.await_confirmation(task.id, prompt)
        if task.status == TaskStatus.AWAITING_CONFIRMATION:
            self.tasks.set_confirmation_context(
                task.id,
                confirmation_intent=intent,
                confirmation_steps=[{"tool": tool, "arguments": arguments} for tool, arguments in steps],
                confirmation_requested_at=time(),
            )
        self._pending_confirmation = PendingConfirmation(task.id, text, intent, steps, action=action, messages=messages or [])
        return prompt

    def _resume_pending_confirmation(self, max_attempts: int) -> AgentResult:
        pending = self._pending_confirmation
        if pending is None:
            raise RuntimeError("Não há confirmação pendente")
        self._pending_confirmation = None
        task = self.tasks.get(pending.task_id)
        if task is None or task.status != TaskStatus.AWAITING_CONFIRMATION:
            return AgentResult("A ação pendente não está mais disponível para confirmação.")

        if pending.intent == "autonomous" and pending.action is not None:
            return self._handle_autonomous(pending.text, task=task, resume=pending)

        report = self.correction.run(
            task,
            lambda error, attempt: self._correct_steps(pending.text, pending.steps, error, attempt),
            max_attempts=max_attempts,
            confirmed=True,
        )
        return self._report_result(task, pending.text, pending.intent, report)

    # ------------------------------------------------------------ execução

    def _validated_tool_steps(self, steps) -> list[tuple[str, dict[str, Any]]]:
        validated: list[tuple[str, dict[str, Any]]] = []
        for step in steps:
            if step.kind != StepKind.TOOL or not step.tool:
                continue
            arguments = step.arguments or {}
            if self.schemas.validate(step.tool, arguments).valid:
                validated.append((step.tool, arguments))
        return validated

    def _autonomous_enabled(self) -> bool:
        return os.getenv("DUQUE_AUTONOMOUS_AGENT", "0").casefold() in {"1", "true", "yes", "on"} and self.online

    @staticmethod
    def _autonomous_requested(text: str) -> bool:
        value = " ".join(text.casefold().strip().split())
        markers = (
            "analise o projeto", "analisa o projeto", "analise o código", "analisa o código",
            "revise o projeto", "revisar o projeto", "investigue o projeto", "investiga o projeto",
            "verifique o projeto", "verifica o projeto", "encontre os problemas", "procure os problemas",
            "veja o que está errado", "veja o que esta errado", "trabalhe nisso",
            "faça o que for necessário", "faca o que for necessario",
        )
        return any(marker in value for marker in markers)

    @staticmethod
    def _execution_message(value: object) -> str | None:
        """Mensagem para os formatos de resultado conhecidos; None quando desconhecido."""
        if isinstance(value, ExecutionResult):
            if not value.success:
                return value.error
            value = value.value
        if not isinstance(value, dict):
            return None
        if "workspace" in value and "file_count" in value:
            return f"Workspace: {value['workspace']}\nArquivos encontrados: {value['file_count']}."
        if "files" in value and isinstance(value["files"], list):
            files = [str(item) for item in value["files"]]
            if not files:
                return "O workspace está vazio."
            shown = files[:40]
            suffix = f" ... e mais {len(files) - 40}" if len(files) > 40 else ""
            return f"Encontrei {len(files)} arquivo(s):\n" + "\n".join(f"- {item}" for item in shown) + suffix
        if "content" in value and "path" in value:
            content = str(value["content"])
            if len(content) > 6000:
                content = content[:6000] + "\n...[conteúdo truncado]"
            return f"Arquivo: {value['path']}\n\n{content}"
        if value.get("already_running") is True and "app" in value:
            return f"O {value['app']} já está aberto."
        if value.get("opened") is True and "app" in value:
            return f"Abri o aplicativo {value.get('app', 'solicitado')}."
        if "closed" in value and "app" in value:
            if value.get("closed") is True:
                return f"Fechei o aplicativo {value.get('app', 'solicitado')}."
            if value.get("still_running"):
                return f"Pedi para fechar o {value.get('app', 'aplicativo')}, mas ele continua aberto (talvez esteja pedindo para salvar)."
            return f"O aplicativo {value.get('app', 'solicitado')} já não estava aberto."
        if "running" in value and "app" in value:
            status = "está aberto" if value.get("running") else "não está aberto"
            return f"{value.get('app', 'O aplicativo')} {status}."
        if value.get("created") is True:
            return f"Criei o arquivo {value.get('path', 'solicitado')}."
        if value.get("deleted") is True:
            return f"Excluí o arquivo {value.get('path', 'solicitado')}."
        if "query" in value and "results" in value and isinstance(value["results"], list):
            results = value["results"]
            if not results:
                return f"Nenhum resultado encontrado para: {value['query']}"
            lines = [f"Pesquisa: {value['query']}"]
            for index, item in enumerate(results[:8], 1):
                if isinstance(item, dict):
                    lines.append(f"{index}. {item.get('title', 'Sem título')} — {item.get('url', '')}")
            return "\n".join(lines)
        if value.get("opened") is True and "index" in value and "title" in value:
            return f"Abri o resultado {value['index']}: {value['title']}"
        if value.get("opened") is True and "url" in value:
            return f"Abri {value['url']}."
        if value.get("scheduled") is True:
            return f"Agendado: {value.get('description', '')}."
        if value.get("cancelled") is True and "job_id" in value:
            return "Agendamento cancelado."
        if "stdout" in value and "success" in value:
            return str(value.get("stdout") or value.get("stderr") or "").strip() or None
        return None

    def _report_result(self, task: Task, text: str, intent: str, report) -> AgentResult:
        if report.success:
            last = report.results[-1].result if report.results else None
            if intent in {"open_app", "close_app", "check_app"}:
                for tool_name, arguments in report.last_steps:
                    app_name = arguments.get("name")
                    if tool_name in {"open_app", "close_app", "is_app_running"} and isinstance(app_name, str) and app_name.strip():
                        self._last_app = app_name.strip()
                        self._last_app_at = time()
                        break
            message = self._execution_message(last)
            if message is None:
                message = self._summarize(text, last.value if last is not None else None)
            self.memory.remember(MemoryLayer.OPERATIONAL, f"task:{task.id}", {"description": text, "status": "completed", "attempts": report.attempts, "response": message[:500]})
            return AgentResult(message, task.id, last, report.attempts)

        failed = next((item for item in reversed(report.results) if not item.result.success), None)
        if failed and failed.result.confirmation_required:
            remaining = report.last_steps[failed.index - 1:] if report.last_steps else []
            prompt = self._await_confirmation(task, text, intent, remaining or [(failed.tool, {})])
            return AgentResult(prompt, task.id, failed.result, report.attempts, awaiting_confirmation=True)
        error = report.last_error or (failed.result.error if failed else "Falha desconhecida")
        self.memory.remember(MemoryLayer.OPERATIONAL, f"task:{task.id}", {"description": text, "status": "failed", "error": error, "attempts": report.attempts})
        return AgentResult(f"Não consegui executar a tarefa: {error}", task.id, failed.result if failed else None, report.attempts)

    def _run_steps(self, task: Task, text: str, intent: str, tool_steps: list[tuple[str, dict[str, Any]]], max_attempts: int) -> AgentResult:
        report = self.correction.run(
            task,
            lambda error, attempt: self._correct_steps(text, tool_steps, error, attempt),
            max_attempts=max_attempts,
        )
        return self._report_result(task, text, intent, report)

    def _handle_autonomous(self, text: str, *, task: Task | None = None, resume: PendingConfirmation | None = None) -> AgentResult:
        if task is None:
            task = self.tasks.create(text, mode="autonomous")
        context = AgentContext(goal=text, task_id=task.id)
        try:
            self.tasks.start(task.id)
            if resume is not None:
                result = self.autonomous.run(context, resume_messages=resume.messages, approved_action=resume.action)
            else:
                result = self.autonomous.run(context)
            last = result.executions[-1] if result.executions else None
            if result.success:
                self.tasks.complete(task.id, result.message)
                self.memory.remember(MemoryLayer.OPERATIONAL, f"task:{task.id}", {"description": text, "status": "completed", "mode": "autonomous", "steps": result.steps})
                return AgentResult(result.message, task.id, last, result.steps or 1)
            if result.pending_action is not None:
                prompt = self._await_confirmation(task, text, "autonomous", [result.pending_action], action=result.pending_action, messages=result.messages)
                return AgentResult(prompt, task.id, last, result.steps or 1, awaiting_confirmation=True)
            if task.status == TaskStatus.RUNNING:
                self.tasks.fail(task.id, result.error or result.message or "Falha no agente autônomo")
            return AgentResult(result.message or f"Não consegui concluir a tarefa: {result.error}", task.id, last, result.steps or 1)
        except Exception as exc:
            if task.status == TaskStatus.RUNNING:
                self.tasks.fail(task.id, f"{type(exc).__name__}: {exc}")
            return AgentResult(f"O agente encontrou um erro: {type(exc).__name__}: {exc}", task.id)

    def _chat(self, task: Task, text: str, answer: str | None = None) -> AgentResult:
        self.tasks.start(task.id)
        try:
            answer = answer or self._chat_response(text)
        except Exception as exc:
            error = f"Não consegui gerar uma resposta: {type(exc).__name__}: {exc}"
            self.tasks.fail(task.id, error)
            return AgentResult(error, task.id)
        self.tasks.complete(task.id, answer)
        self.engine.emit(EventType.RESPONSE_STARTED, task_id=task.id)
        self.engine.emit(EventType.RESPONSE_FINISHED, task_id=task.id)
        return AgentResult(answer, task.id)

    def handle(self, text: str, *, max_attempts: int = 3) -> AgentResult:
        # Um pedido por vez: dois pedidos (ou um pedido e a agenda) agindo ao
        # mesmo tempo disputam mouse, teclado e a confirmação pendente.
        with self._lock:
            result = self._handle(text, max_attempts)
            self._history.append({"role": "user", "content": text[:2000]})
            self._history.append({"role": "assistant", "content": result.text[:2000]})
            return result

    def _handle(self, text: str, max_attempts: int) -> AgentResult:
        self.memory.remember(MemoryLayer.CONVERSATION, f"turn:{uuid4().hex}", {"role": "user", "text": text})
        notice = ""
        pending = self._pending_confirmation
        if pending is not None:
            if pending.expired():
                self._cancel_pending("expired")
                notice = "A ação que esperava confirmação expirou e foi cancelada. "
            elif self._is_confirmation(text):
                return self._resume_pending_confirmation(max_attempts)
            elif self._is_cancellation(text):
                cancelled = self._cancel_pending("user_confirmation_denied")
                return AgentResult("Certo. Ação cancelada.", cancelled.task_id if cancelled else None)
            else:
                # Mudou de assunto: a ação pendente não pode ficar travando o Duque.
                self._cancel_pending("superseded")
                notice = "Cancelei a ação que esperava confirmação. "

        result = self._dispatch(text, max_attempts)
        if notice:
            result.text = notice + result.text
        return result

    def _dispatch(self, text: str, max_attempts: int) -> AgentResult:
        if self._last_app and time() - self._last_app_at > LAST_APP_TTL_SECONDS:
            self._last_app = None
        route = self.router.route(text, self._last_app)
        intent = route.intent.value
        if self._autonomous_enabled() and self._autonomous_requested(text):
            return self._handle_autonomous(text)

        task = self.tasks.create(text, intent=intent, confidence=route.confidence)
        self.memory.remember(MemoryLayer.OPERATIONAL, f"task:{task.id}", {"description": text, "status": "created"})

        if intent in DETERMINISTIC_INTENTS:
            plan = self.planner.build(text, intent, set(self.schemas.names()), self._last_app)
            tool_steps = self._validated_tool_steps(plan.steps)
            if tool_steps:
                return self._run_steps(task, text, intent, tool_steps, max_attempts)
            if not self.online:
                self.tasks.start(task.id)
                error = f"Não entendi o que fazer com: {text}"
                self.tasks.fail(task.id, error)
                return AgentResult(error, task.id)

        if not self.online:
            return self._chat(task, text, OFFLINE_MESSAGE)
        try:
            plan = self.model_planner.build(text, self.executor.tools.names(), list(self._history))
        except Exception:
            # Plano inválido do modelo: responde como conversa em vez de agir.
            return self._chat(task, text)
        tool_steps = self._validated_tool_steps(plan.steps)
        if tool_steps:
            return self._run_steps(task, text, intent, tool_steps, max_attempts)
        return self._chat(task, text, plan.answer)

    def _correct_steps(
        self,
        goal: str,
        original_steps: list[tuple[str, dict[str, Any]]],
        error: str | None,
        attempt: int,
    ) -> list[tuple[str, dict[str, Any]]]:
        if not error:
            return original_steps
        if not self.online:
            # Sem modelo não há como reescrever o plano a partir do erro.
            return original_steps
        correction_goal = (
            f"Objetivo original: {goal}\n"
            f"Falha da tentativa {attempt}: {error}\n"
            "Crie um novo plano corrigido."
        )
        try:
            plan = self.model_planner.build(correction_goal, self.executor.tools.names())
            return self._validated_tool_steps(plan.steps) or original_steps
        except Exception:
            return original_steps
