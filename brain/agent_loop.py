from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass
from threading import RLock
from typing import Any
from uuid import uuid4

from automation.runner import ScheduledTaskRunner
from automation.scheduler import Scheduler
from core.emergency import EmergencyPause, emergency
from core.engine import DuqueEngine
from core.events import EventType
from core.executor import ExecutionResult, Executor
from core.task_engine import TaskEngine
from core.tasks import Task, TaskManager
from computer.code_tools import CodeTools
from computer.runtime import create_ui_tools, create_verification
from computer.screen_tools import ScreenTools
from computer.system_tools import SystemTools
from computer.tools import ComputerTools
from computer.ui_tools import UITools
from computer.verification_tools import VerificationTools
from computer.verified_ui import VerifiedScreenActions
from computer.visual_workflow import VisualWorkflow
from computer.workspace import Workspace
from computer.assistant_tools import AssistantTools
from computer.messaging import Messaging
from computer.notepad import NotepadWriter
from computer.whatsapp_flow import WhatsAppDesktop
from computer.now_playing import NowPlaying
from computer.screen_vision import ScreenVision
from memory.conversation import ConversationStore
from memory.memory import Memory, MemoryLayer
from .agent_state import AgentContext
from .compound import plan_steps, strip_name
from .operator import OPERATOR_SYSTEM, looks_like_action
from .planner import WHATSAPP_ACTION
from .autonomous_loop import AutonomousLoop
from .model import ModelAdapter, NullModel, OllamaModel, default_model
from .persona import text_system_prompt
from .routines import Routines
from .voice_style import list_voices, set_voice
from .when import describe_moment, parse_when
from .model_planner import ModelPlanner
from .planner import Planner, StepKind
from .router import IntentRouter
from .self_correction import SelfCorrection
from .self_development import SelfDevelopment
from .tool_schema import ToolSchemaRegistry, ToolSpec


@dataclass(slots=True)
class AgentResult:
    text: str
    task_id: str | None = None
    execution: ExecutionResult | None = None
    attempts: int = 1


@dataclass(slots=True)
class PendingConfirmation:
    task_id: str
    text: str
    intent: str
    steps: list[tuple[str, dict[str, object]]]


_CREATE_TEXT = re.compile(
    r"^(?:por favor[,]?\s+)?(?:cri[ae]|criar|fa[çc]a|fazer|escrev[ae]|escrever|componh[ao]|redij[ao]|mont[ae]|ger[ae]|elabor[ae])\s+"
    r"(?:para mim\s+)?(?=(?:um[a]?s?\s+)?(?:pequen[oa]\s+|curt[oa]\s+|bel[oa]\s+)?"
    r"(?:poema|poesia|soneto|haicai|texto|carta|hist[oó]ria|conto|mensagem|resumo|piada|receita|e-?mail|par[aá]grafo|frase|discurso|letra|legenda|bilhete|cr[oô]nica|pensamento|reflex[aã]o|lista)\b)",
    re.IGNORECASE,
)
_SAVE_TO_NOTEPAD = re.compile(
    r"^(?:por favor[,]?\s+)?(?:salv[ae]|guard[ae]|coloqu?e|p[oõ]e|ponha|escrev[ae]|anot[ae]|cole)\s+(?:(?:isso|ele|ela|o poema|a poesia|o texto|a carta|tudo|o que (?:voc[eê] )?(?:escreveu|criou))\s+)?(?:n[oa]|no)\s+(?:bloco de notas|notepad)\s*[.!]?\s*$",
    re.IGNORECASE,
)
_DEPENDS_ON_PREVIOUS = re.compile(r"\b(?:l[aá]|nele|nela|neles|nelas|ali|a[ií]|isso|ele|ela|o mesmo)\b", re.IGNORECASE)


class AgentLoop:
    """Orquestra entendimento, planejamento, execução, verificação, correção, memória e agenda."""

    def __init__(self, engine: DuqueEngine | None = None, tasks: TaskManager | None = None, executor: Executor | None = None, workspace: Workspace | None = None, ui_tools: UITools | None = None, model: ModelAdapter | None = None, model_planner: ModelPlanner | None = None, memory: Memory | None = None, forge_service: Any | None = None, pause: EmergencyPause | None = None) -> None:
        self.engine = engine or DuqueEngine()
        self.pause = pause if pause is not None else emergency
        self.router = IntentRouter()
        self.planner = Planner()
        self.tasks = tasks or TaskManager()
        self.verification = create_verification()
        self.executor = executor or Executor(self.tasks, verification=self.verification, event_sink=self.engine.emit)
        self.executor.pause = self.pause
        self.workspace = workspace or Workspace(os.getenv("DUQUE_WORKSPACE_ROOT", "."))
        ComputerTools().register(self.executor)
        CodeTools(self.workspace).register(self.executor)
        SystemTools().register(self.executor)
        self.self_development = SelfDevelopment(self.workspace)
        self.self_development.register(self.executor)
        active_ui_tools = ui_tools or create_ui_tools()
        active_ui_tools.register(self.executor)
        self.ui_controller = active_ui_tools.controller
        if self.verification is not None:
            VerificationTools(self.verification).register(self.executor)
            ScreenTools(self.verification).register(self.executor)
            verified_actions = VerifiedScreenActions(active_ui_tools.controller, self.verification)
            verified_actions.register(self.executor)
            self.visual_workflow = VisualWorkflow(verified_actions, self.verification)
        else:
            self.visual_workflow = None
        self.task_engine = TaskEngine(self.executor, self.tasks, self.engine.emit)
        self.correction = SelfCorrection(self.task_engine)
        self.model = model or self._create_default_model()
        self.schemas = ToolSchemaRegistry()
        self.executor.register("schedule_task", self._schedule_task)
        self._register_tool_schemas()
        self.model_planner = model_planner or ModelPlanner(self.model, self.schemas)
        self.autonomous = AutonomousLoop(self.model, self.executor, self.schemas, observer=self._observe_screen, event_sink=self.engine.emit)
        self.operator = AutonomousLoop(self.model, self.executor, self.schemas, max_steps=30, event_sink=self.engine.emit, system=OPERATOR_SYSTEM, time_limit=360)
        self.memory = memory or Memory()
        self.conversation = ConversationStore(self.memory)
        self._handle_lock = RLock()
        self.assistant_tools = AssistantTools(self.memory, notify=self.announce)
        self.assistant_tools.register(self.executor, self.schemas)
        self._pending_confirmation: PendingConfirmation | None = None
        self._last_app: str | None = None
        self._restore_pending_confirmation()
        self.forge_service = forge_service if forge_service is not None else self._create_forge_service()
        if self.forge_service is not None:
            self.executor.register("forge_improve", self._forge_improve)
            self.executor.register("forge_status", self.forge_service.status)
            self.schemas.register(ToolSpec("forge_improve", "Melhora o próprio código do Duque com segurança: cópia isolada, testes, PR, CI e atualização automática", ("goal",), {"goal": str}))
            self.schemas.register(ToolSpec("forge_status", "Consulta o andamento dos trabalhos da Forja"))
        self.scheduler = Scheduler(database=self.tasks.database)
        self.scheduled_runner = ScheduledTaskRunner(self.scheduler, self.task_engine, self.tasks, event_sink=self.engine.emit, reminder_handler=self._on_reminder)
        self.scheduled_runner.pause = self.pause
        if self.forge_service is not None and hasattr(self.forge_service, "pause"):
            self.forge_service.pause = self.pause
        self.now_playing = NowPlaying()
        self.screen_vision = ScreenVision()
        self._focus_until: float | None = None
        self._focus_timer: threading.Timer | None = None
        self._register_life_tools()
        self._ensure_daily_summary()
        self.scheduled_runner.start()

    def _create_forge_service(self) -> Any | None:
        if os.getenv("DUQUE_FORGE", "1").casefold() in {"0", "false", "no", "off", "nao", "não"}:
            return None
        if not (self.workspace.root / ".git").exists():
            return None
        try:
            from forge.config import ForgeConfig
            from forge.forge import Forge
            from forge.service import ForgeService
            from forge.updater import Updater
            from .providers.factory import create_developer_model
            model = create_developer_model()
            if model is None:
                return None
            config = ForgeConfig.from_env(self.workspace.root)
            forge = Forge.create(config, model, self.tasks)
            updater = Updater(config.repo_root, remote=config.remote, base_branch=config.base_branch)
            return ForgeService(forge, updater, notify=self._forge_notify)
        except Exception as exc:
            self.memory.remember(MemoryLayer.OPERATIONAL, "forge:disabled", {"error": f"{type(exc).__name__}: {exc}"})
            return None

    def _forge_notify(self, kind: str, data: dict[str, Any]) -> None:
        self.memory.remember(MemoryLayer.OPERATIONAL, f"forge:{kind}:{uuid4().hex[:8]}", data)
        if kind == "forja_concluida":
            self.announce(self.forge_announcement(data))

    @staticmethod
    def forge_announcement(data: dict[str, Any]) -> str:
        goal = str(data.get("goal", "")).strip(); status = data.get("status")
        text = {"merged": f"Du, terminei na Forja: {goal}. Passou nos testes e no CI e já está no main.", "awaiting_approval": f"Du, a melhoria '{goal}' está pronta, mas precisa da sua aprovação no GitHub.", "no_changes": f"Du, analisei '{goal}' na Forja e não foi preciso mudar nada."}.get(str(status), f"Du, não consegui concluir '{goal}' na Forja. Os detalhes estão no relatório.")
        if data.get("restarting"): text += " Vou reiniciar em alguns segundos para aplicar."
        elif data.get("update") == "rolled_back": text += " A atualização falhou na validação local e voltei para a versão anterior."
        return text

    def _register_tool_schemas(self) -> None:
        specs = [
            ToolSpec("open_app", "Abre um aplicativo", ("name",), {"name": str}), ToolSpec("close_app", "Fecha um aplicativo pelo processo conhecido", ("name",), {"name": str}), ToolSpec("is_app_running", "Verifica se um aplicativo está em execução", ("name",), {"name": str}),
            ToolSpec("open_url", "Abre uma URL no navegador; pode ser usada para serviços web como WhatsApp Web", ("url",), {"url": str}), ToolSpec("open_path", "Abre um caminho existente", ("path",), {"path": str}), ToolSpec("web_search", "Pesquisa na web sem abrir o navegador (se falhar, abre o Google)", ("query",), {"query": str}), ToolSpec("google_search", "Abre a pesquisa do Google no navegador", ("query",), {"query": str}), ToolSpec("open_search_result", "Abre no navegador um resultado da pesquisa recente", (), {"index": int}),
            ToolSpec("read_file", "Lê um arquivo do workspace", ("path",), {"path": str}), ToolSpec("read_many_files", "Lê vários arquivos do workspace", ("paths",), {"paths": list}), ToolSpec("write_file", "Escreve arquivo no workspace", ("path", "content"), {"path": str, "content": str}), ToolSpec("delete_file", "Exclui um arquivo do workspace", ("path",), {"path": str}), ToolSpec("apply_code_change", "Aplica uma alteração de código somente quando a auto-modificação estiver explicitamente habilitada", ("path", "content"), {"path": str, "content": str}), ToolSpec("list_files", "Lista arquivos do workspace"), ToolSpec("inspect_workspace", "Inspeciona a estrutura do workspace"), ToolSpec("run_tests", "Executa a suíte de testes do workspace", (), {"path": str}), ToolSpec("run_python", "Executa Python no workspace", ("path",), {"path": str}),
            ToolSpec("git_status", "Consulta o estado do repositório Git sem alterar arquivos"), ToolSpec("git_diff", "Consulta diferenças locais do repositório Git", (), {"path": str}), ToolSpec("git_log", "Consulta o histórico recente do Git", (), {"limit": int}), ToolSpec("git_fetch", "Atualiza referências remotas do Git sem alterar o working tree"), ToolSpec("git_pull", "Atualiza o workspace pelo remoto usando fast-forward"), ToolSpec("git_commit", "Cria um commit com as alterações atuais", ("message",), {"message": str}), ToolSpec("git_push", "Envia commits para um remoto Git", (), {"remote": str, "branch": str}),
            ToolSpec("ui_click", "Clica na tela", ("x", "y"), {"x": int, "y": int}), ToolSpec("ui_type_text", "Digita texto", ("text",), {"text": str}), ToolSpec("ui_press", "Pressiona uma tecla", ("key",), {"key": str}), ToolSpec("ui_hotkey", "Pressiona combinação de teclas", ("keys",), {"keys": list}), ToolSpec("screenshot", "Captura a tela"), ToolSpec("screen_snapshot", "Observa a tela com contexto semântico"), ToolSpec("screen_find", "Localiza um elemento visual por texto", ("text",), {"text": str}), ToolSpec("screen_click_text", "Localiza um texto na tela e clica no elemento; pode confirmar texto esperado", ("text",), {"text": str, "expected_text": str, "expected_not_text": str}), ToolSpec("screen_contains_text", "Verifica se um texto está visível via OCR", ("text",), {"text": str}),
            ToolSpec("schedule_task", "Agenda uma tarefa serializável", ("description", "delay_seconds", "steps"), {"description": str, "delay_seconds": (int, float), "steps": list, "repeat_seconds": (int, float)}), ToolSpec("system_info", "Obtém informações do sistema local"), ToolSpec("environment", "Lê uma variável de ambiente ou o ambiente completo", (), {"name": str}), ToolSpec("list_directory", "Lista qualquer diretório local", (), {"path": str}), ToolSpec("read_any_file", "Lê qualquer arquivo local", ("path",), {"path": str, "max_bytes": int}), ToolSpec("write_any_file", "Escreve qualquer arquivo local", ("path", "content"), {"path": str, "content": str}), ToolSpec("write_desktop_file", "Cria um arquivo somente na Área de Trabalho", ("filename", "content"), {"filename": str, "content": str}), ToolSpec("delete_any_file", "Exclui arquivo ou diretório local", ("path",), {"path": str}), ToolSpec("copy_path", "Copia arquivo ou diretório local", ("source", "destination"), {"source": str, "destination": str}), ToolSpec("move_path", "Move arquivo ou diretório local", ("source", "destination"), {"source": str, "destination": str}), ToolSpec("run_command", "Executa um comando do sistema local", ("command",), {"command": str, "timeout": int}), ToolSpec("list_processes", "Lista processos em execução"), ToolSpec("kill_process", "Encerra um processo local", ("pid",), {"pid": int, "force": bool}),
        ]
        registered = set(self.executor.tools.names())
        for spec in specs:
            if spec.name in registered:
                self.schemas.register(spec)
