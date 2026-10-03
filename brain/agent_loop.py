from __future__ import annotations

import os
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
from computer.now_playing import NowPlaying
from computer.screen_vision import ScreenVision
from memory.conversation import ConversationStore
from memory.memory import Memory, MemoryLayer
from .agent_state import AgentContext
from .compound import plan_steps, strip_name
from .autonomous_loop import AutonomousLoop
from .model import ModelAdapter, NullModel, OpenAIResponsesModel
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


class AgentLoop:
    """Orquestra entendimento, planejamento, execução, verificação, correção, memória e agenda."""

    def __init__(self, engine: DuqueEngine | None = None, tasks: TaskManager | None = None, executor: Executor | None = None, workspace: Workspace | None = None, ui_tools: UITools | None = None, model: ModelAdapter | None = None, model_planner: ModelPlanner | None = None, memory: Memory | None = None, forge_service: Any | None = None, pause: EmergencyPause | None = None) -> None:
        self.engine = engine or DuqueEngine()
        # Pausa de emergência única do TELEX (botão do HUD, "pausa tudo", F9).
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
            self.schemas.register(ToolSpec(
                "forge_improve",
                "Melhora o próprio código do Duque com segurança: cópia isolada, testes, PR, CI e atualização automática",
                ("goal",),
                {"goal": str},
            ))
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
        """Liga a Forja quando há repositório Git e um modelo programador configurado."""
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
        """Frase curta para avisar, por voz, o resultado de um trabalho da Forja."""
        goal = str(data.get("goal", "")).strip()
        status = data.get("status")
        text = {
            "merged": f"Du, terminei na Forja: {goal}. Passou nos testes e no CI e já está no main.",
            "awaiting_approval": f"Du, a melhoria '{goal}' está pronta, mas precisa da sua aprovação no GitHub.",
            "no_changes": f"Du, analisei '{goal}' na Forja e não foi preciso mudar nada.",
        }.get(str(status), f"Du, não consegui concluir '{goal}' na Forja. Os detalhes estão no relatório.")
        if data.get("restarting"):
            text += " Vou reiniciar em alguns segundos para aplicar."
        elif data.get("update") == "rolled_back":
            text += " A atualização falhou na validação local e voltei para a versão anterior."
        return text

    def memory_digest(self, limit: int = 25) -> str:
        """Anotações do Du em texto curto, para o modelo lembrar dele."""
        notes = self.assistant_tools.notes_list().get("notes", [])
        return "\n".join(f"- {note['text']}" for note in notes[-limit:])

    def greeting(self) -> str:
        """Saudação de início, no estilo J.A.R.V.I.S.: hora, clima e pendências."""
        from datetime import datetime

        now = datetime.now()
        period = "Bom dia" if 5 <= now.hour < 12 else "Boa tarde" if 12 <= now.hour < 18 else "Boa noite"
        parts = [f"{period}, Du. São {now:%H:%M}."]
        try:
            weather = self.assistant_tools.weather()
            if weather.get("message"):
                parts.append(str(weather["message"]))
        except Exception:
            pass
        timers = self.assistant_tools.timers_list().get("timers", [])
        if timers:
            parts.append(f"Você tem {len(timers)} timer(s) ativo(s).")
        notes = self.assistant_tools.notes_list().get("notes", [])
        if notes:
            parts.append(f"{len(notes)} anotação(ões) guardada(s).")
        if self.forge_service is not None:
            history = self.forge_service.status().get("history") or []
            if history and history[-1].get("status") == "merged":
                parts.append(f"Última melhoria aplicada pela Forja: {history[-1].get('goal')}.")
        parts.append("Sistemas online.")
        return " ".join(parts)

    def _forge_improve(self, goal: str) -> dict[str, object]:
        if self.forge_service is None:
            return {"success": False, "error": "A Forja não está ativa"}
        return {"queued": True, **self.forge_service.submit(goal)}

    @staticmethod
    def _forge_status_requested(text: str) -> bool:
        value = " ".join(text.casefold().split())
        return "forja" in value and any(word in value for word in ("status", "andamento", "como está", "como esta", "progresso", "terminou", "o que está fazendo", "o que esta fazendo"))

    def _forge_status_text(self) -> str:
        if self.forge_service is None:
            return "A Forja não está ativa."
        status = self.forge_service.status()
        current = status.get("current")
        parts = []
        if current:
            parts.append(f"Trabalhando em: {current.get('goal')} (etapa: {current.get('step', 'iniciando')}).")
        if status.get("queued"):
            parts.append(f"{status['queued']} pedido(s) na fila.")
        history = status.get("history") or []
        if history:
            parts.append("Último resultado: " + str(history[-1].get("summary", "")).splitlines()[0])
        return " ".join(parts) or "A Forja está parada, sem pedidos."

    @staticmethod
    def _forge_requested(text: str) -> bool:
        """Pedidos para o Duque MUDAR o próprio código vão para a Forja.

        Precisa de um verbo de mudança + o próprio Duque como alvo (ou citar a
        Forja explicitamente). Perguntas como "explica seu código" não contam.
        """
        import re

        value = " ".join(text.casefold().strip().split())
        if "forja" in value and not re.search(r"\b(?:como|status|andamento|progresso)\b", value):
            return True
        if re.search(r"\bse (?:melhore|melhora|atualize|atualiza|corrija|corrige|evolua|evolui|aprimore)\b|\b(?:melhore|evolua|aprimore) a si\b", value):
            return True
        verb = re.search(r"\b(?:melhor|corrij|corrig|reescrev|evolu|atualiz|implement|adicion|cri[ae]\b|refator|consert|arrum|otimiz|aprimor|mud[ae]\b|alter)\w*", value)
        target = re.search(
            r"\b(?:seu (?:próprio |proprio )?(?:código|codigo)|(?:você|voce) mesmo|a si mesmo|o projeto|(?:no|ao|o) duque|(?:sua|suas) (?:função|funcao|funções|funcoes|ferramentas?))\b",
            value,
        )
        return bool(verb and target)

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
        specs = [
            ToolSpec("open_app", "Abre um aplicativo", ("name",), {"name": str}),
            ToolSpec("close_app", "Fecha um aplicativo pelo processo conhecido", ("name",), {"name": str}),
            ToolSpec("is_app_running", "Verifica se um aplicativo está em execução", ("name",), {"name": str}),
            ToolSpec("open_url", "Abre uma URL no navegador; pode ser usada para serviços web como WhatsApp Web", ("url",), {"url": str}),
            ToolSpec("open_path", "Abre um caminho existente", ("path",), {"path": str}),
            ToolSpec("web_search", "Pesquisa na web sem abrir o navegador (se falhar, abre o Google)", ("query",), {"query": str}),
            ToolSpec("google_search", "Abre a pesquisa do Google no navegador", ("query",), {"query": str}),
            ToolSpec("open_search_result", "Abre no navegador um resultado da pesquisa recente", (), {"index": int}),
            ToolSpec("read_file", "Lê um arquivo do workspace", ("path",), {"path": str}),
            ToolSpec("read_many_files", "Lê vários arquivos do workspace", ("paths",), {"paths": list}),
            ToolSpec("write_file", "Escreve arquivo no workspace", ("path", "content"), {"path": str, "content": str}),
            ToolSpec("delete_file", "Exclui um arquivo do workspace", ("path",), {"path": str}),
            ToolSpec("apply_code_change", "Aplica uma alteração de código somente quando a auto-modificação estiver explicitamente habilitada", ("path", "content"), {"path": str, "content": str}),
            ToolSpec("list_files", "Lista arquivos do workspace"),
            ToolSpec("inspect_workspace", "Inspeciona a estrutura do workspace"),
            ToolSpec("run_tests", "Executa a suíte de testes do workspace", (), {"path": str}),
            ToolSpec("run_python", "Executa Python no workspace", ("path",), {"path": str}),
            ToolSpec("git_status", "Consulta o estado do repositório Git sem alterar arquivos"),
            ToolSpec("git_diff", "Consulta diferenças locais do repositório Git", (), {"path": str}),
            ToolSpec("git_log", "Consulta o histórico recente do Git", (), {"limit": int}),
            ToolSpec("git_fetch", "Atualiza referências remotas do Git sem alterar o working tree"),
            ToolSpec("git_pull", "Atualiza o workspace pelo remoto usando fast-forward"),
            ToolSpec("git_commit", "Cria um commit com as alterações atuais", ("message",), {"message": str}),
            ToolSpec("git_push", "Envia commits para um remoto Git", (), {"remote": str, "branch": str}),
            ToolSpec("ui_click", "Clica na tela", ("x", "y"), {"x": int, "y": int}),
            ToolSpec("ui_type_text", "Digita texto", ("text",), {"text": str}),
            ToolSpec("ui_press", "Pressiona uma tecla", ("key",), {"key": str}),
            ToolSpec("ui_hotkey", "Pressiona combinação de teclas", ("keys",), {"keys": list}),
            ToolSpec("screenshot", "Captura a tela"),
            ToolSpec("screen_snapshot", "Observa a tela com contexto semântico"),
            ToolSpec("screen_find", "Localiza um elemento visual por texto", ("text",), {"text": str}),
            ToolSpec("screen_click_text", "Localiza um texto na tela e clica no elemento; pode confirmar texto esperado", ("text",), {"text": str, "expected_text": str, "expected_not_text": str}),
            ToolSpec("screen_contains_text", "Verifica se um texto está visível via OCR", ("text",), {"text": str}),
            ToolSpec("schedule_task", "Agenda uma tarefa serializável", ("description", "delay_seconds", "steps"), {"description": str, "delay_seconds": (int, float), "steps": list, "repeat_seconds": (int, float)}),
            ToolSpec("system_info", "Obtém informações do sistema local"),
            ToolSpec("environment", "Lê uma variável de ambiente ou o ambiente completo", (), {"name": str}),
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

    def _schedule_task(self, description: str, delay_seconds: int | float, steps: list[dict[str, object]], repeat_seconds: int | float | None = None) -> dict[str, object]:
        if not isinstance(description, str) or not description.strip():
            raise ValueError("description não pode ser vazio")
        if not isinstance(steps, list) or not steps:
            raise ValueError("steps deve conter pelo menos uma etapa")
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
            validation = self.schemas.validate(tool, arguments)
            if not validation.valid:
                raise ValueError(validation.error or f"Etapa inválida: {tool}")
            normalized.append({"tool": tool, "arguments": arguments})
        task = self.tasks.create(description, source="scheduled", scheduled=True)
        job = self.scheduler.add_task_after(description, max(0, float(delay_seconds)), task_id=task.id, steps=normalized, repeat_seconds=float(repeat_seconds) if repeat_seconds is not None else None)
        return {"job_id": job.id, "task_id": task.id, "description": description, "run_at": job.run_at}

    @staticmethod
    def _create_default_model() -> ModelAdapter:
        """Usa o modelo da API quando a chave estiver configurada; caso contrário, permanece offline."""
        if os.getenv("OPENAI_API_KEY"):
            try:
                return OpenAIResponsesModel()
            except RuntimeError:
                pass
        return NullModel()

    def announce(self, text: str, *, urgent: bool = False) -> None:
        """Aviso espontâneo do Duque (timer, Forja...): entra na conversa e o HUD fala.

        No modo foco os avisos continuam registrados, mas ficam em silêncio.
        """
        channel = "silencioso" if self.focus_active() and not urgent else "aviso"
        self.conversation.add("assistant", text, channel)

    # agenda, foco e visão ----------------------------------------------------
    def _register_life_tools(self) -> None:
        self.notepad = NotepadWriter(None if isinstance(self.model, NullModel) else self._compose_text)
        self.routines = Routines(self.memory, self._run_routine_step, lambda: set(self.schemas.names()))
        self.messaging = Messaging(self.memory, self.assistant_tools.open_target)
        tools = [
            (ToolSpec("routine_run", "Roda uma rotina salva (ex.: 'trabalho', 'estudo', 'jogo')", ("name",), {"name": str}), self.routines.routine_run),
            (ToolSpec("routine_save", "Cria ou substitui uma rotina com comandos separados por vírgula", ("name", "commands"), {"name": str, "commands": str}), self.routines.routine_save),
            (ToolSpec("routines_list", "Lista as rotinas"), self.routines.routines_list),
            (ToolSpec("routine_delete", "Apaga uma rotina", ("name",), {"name": str}), self.routines.routine_delete),
            (ToolSpec("contact_save", "Salva um contato com telefone para o WhatsApp", ("name", "phone"), {"name": str, "phone": str}), self.messaging.contact_save),
            (ToolSpec("contacts_list", "Lista os contatos salvos"), self.messaging.contacts_list),
            (ToolSpec("whatsapp_message", "Abre o WhatsApp com a mensagem pronta para o contato; o Du confere e envia", ("text",), {"contact": str, "text": str}), self.messaging.whatsapp_message),
            (ToolSpec("day_summary", "Resumo do dia: o que foi feito, o que falhou e a agenda de amanhã"), self.day_summary),
            (ToolSpec("set_voice", "Troca a voz do TELEX (ballad, cedar, ash, echo, verse, alloy, marin, sage)", ("name",), {"name": str}), lambda name: set_voice(self.memory, name)),
            (ToolSpec("list_voices", "Lista as vozes disponíveis e a atual"), lambda: list_voices(self.memory)),
            (ToolSpec("reminder_at", "Cria um lembrete em data/hora (ex.: 'amanhã às 9h', 'sexta às 18:30'); sobrevive a reinícios", ("when",), {"when": str, "text": str}), self.reminder_at),
            (ToolSpec("reminders_list", "Lista os lembretes agendados"), self.reminders_list),
            (ToolSpec("reminder_cancel", "Cancela o lembrete de número indicado (0 = todos)", (), {"index": int}), self.reminder_cancel),
            (ToolSpec("focus_mode", "Modo foco/pomodoro: action 'start' (pausa a música e silencia avisos) ou 'stop'", (), {"action": str, "minutes": (int, float)}), self.focus_mode),
            (ToolSpec("describe_screen", "Olha a tela do Du e explica o que há nela (ou responde uma pergunta sobre ela)", (), {"question": str}), self.screen_vision.describe_screen),
            (ToolSpec("notepad_write", "Escreve no Bloco de Notas: um texto ditado ou algo para criar (ex.: 'um poema sobre o mar', 'lista de compras')", ("request",), {"request": str}), self.notepad.notepad_write),
        ]
        for spec, function in tools:
            self.executor.register(spec.name, function)
            self.schemas.register(spec)

    @staticmethod
    def _reminder_subject(text: str) -> str:
        import re

        subject = re.sub(
            r"^(?:duque[,!]?\s+)?(?:me\s+)?(?:lembre|lembra|lembrar|avise|avisa|agende|agenda|marque|marca)(?:-me)?\s*(?:de|que|para|pra|sobre)?\s*",
            "", text.strip(), flags=re.IGNORECASE,
        )
        return subject.strip(" ,.!?") or "o compromisso"

    def reminder_at(self, when: str, text: str = "") -> dict[str, object]:
        from computer.assistant_tools import MAX_REMINDER_TEXT

        if len((text or "").strip()) > MAX_REMINDER_TEXT:
            return {"success": False, "error": "Esse texto parece uma instrução, não um lembrete; peça a tarefa diretamente."}
        parsed = parse_when(when)
        if parsed is None:
            return {"success": False, "error": f"Não entendi a data ou a hora em '{when}'. Diga, por exemplo, 'amanhã às 9h'."}
        if parsed.moment.timestamp() <= time.time():
            return {"success": False, "error": "Esse horário já passou."}
        subject = self._reminder_subject(text or parsed.rest)
        job = self.scheduler.add(subject, parsed.moment, kind="reminder", agenda=True)
        return {
            "message": f"Combinado. {describe_moment(parsed.moment).capitalize()} eu te lembro de {subject}.",
            "id": job.id,
            "at": parsed.moment.isoformat(timespec="minutes"),
        }

    def _agenda(self) -> list[Any]:
        return [job for job in self.scheduler.list() if job.metadata.get("agenda")]

    def reminders_list(self) -> dict[str, object]:
        from datetime import datetime

        jobs = self._agenda()
        if not jobs:
            return {"message": "Sua agenda está vazia.", "reminders": []}
        lines = [f"{index}. {describe_moment(datetime.fromtimestamp(job.run_at))}: {job.description}" for index, job in enumerate(jobs, 1)]
        items = [{"id": job.id, "text": job.description, "at": job.run_at} for job in jobs]
        return {"message": "Na agenda:\n" + "\n".join(lines), "reminders": items}

    def reminder_cancel(self, index: int = 0) -> dict[str, object]:
        jobs = self._agenda()
        if index == 0:
            for job in jobs:
                self.scheduler.cancel(job.id)
            return {"message": f"Cancelei {len(jobs)} lembrete(s).", "cancelled": len(jobs)}
        if not 1 <= index <= len(jobs):
            return {"success": False, "error": f"Não existe o lembrete {index}."}
        job = jobs[index - 1]
        self.scheduler.cancel(job.id)
        return {"message": f"Cancelei o lembrete: {job.description}.", "cancelled": 1}

    def _run_routine_step(self, tool: str, arguments: dict[str, Any]) -> tuple[bool, str]:
        task = self.tasks.create(f"[rotina] {tool}", source="routine")
        result = self.executor.execute_step(task, tool, arguments)
        if result.success:
            return True, self._execution_message(result, f"{tool} ok")
        return False, f"{tool}: {result.error or 'falhou'}"

    def _ensure_daily_summary(self) -> None:
        """Agenda o resumo diário (DUQUE_DAILY_SUMMARY=HH:MM; 0 desliga)."""
        from datetime import datetime, timedelta

        setting = os.getenv("DUQUE_DAILY_SUMMARY", "21:30").strip()
        existing = [job for job in self.scheduler.list() if job.metadata.get("daily_summary")]
        if setting.casefold() in {"0", "off", "false", "nao", "não", ""}:
            for job in existing:
                self.scheduler.cancel(job.id)
            return
        try:
            hour, minute = (int(part) for part in setting.split(":", 1))
        except ValueError:
            return
        if any(job.metadata.get("daily_summary") == setting for job in existing):
            return
        for job in existing:
            self.scheduler.cancel(job.id)
        now = datetime.now()
        first = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if first <= now:
            first += timedelta(days=1)
        self.scheduler.add("resumo do dia", first, kind="reminder", daily_summary=setting, repeat_seconds=86400)

    def day_summary(self) -> dict[str, object]:
        from datetime import datetime, timedelta

        now = datetime.now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        today = [task for task in self.tasks.list() if task.created_at >= start and not str(task.description).startswith("[")]
        done = [task for task in today if task.status.value == "completed"]
        failed = [task for task in today if task.status.value == "failed"]
        actions = [task.description for task in done if task.metadata.get("intent") not in {None, "chat", "unknown"}]
        parts = [f"Resumo do dia, Du: {len(done)} pedido(s) atendido(s)"]
        if actions:
            highlights = list(dict.fromkeys(actions))[-4:]
            parts[0] += ", entre eles: " + "; ".join(highlights)
        parts[0] += "."
        if failed:
            parts.append(f"{len(failed)} não deram certo.")
        if self.forge_service is not None:
            merged = [item for item in self.forge_service.status().get("history") or [] if item.get("status") == "merged"]
            if merged:
                parts.append(f"A Forja aplicou {len(merged)} melhoria(s).")
        tomorrow = (now + timedelta(days=1)).date()
        agenda = [job for job in self._agenda() if datetime.fromtimestamp(job.run_at).date() == tomorrow]
        if agenda:
            items = [f"{datetime.fromtimestamp(job.run_at):%H:%M} {job.description}" for job in agenda]
            parts.append("Amanhã: " + "; ".join(items) + ".")
        else:
            parts.append("Nada na agenda de amanhã.")
        return {"message": " ".join(parts), "done": len(done), "failed": len(failed), "tomorrow": len(agenda)}

    def _on_reminder(self, job: Any) -> None:
        from datetime import datetime

        if job.metadata.get("daily_summary"):
            from datetime import timedelta

            hour, minute = (int(part) for part in str(job.metadata["daily_summary"]).split(":", 1))
            fired = datetime.fromtimestamp(job.last_run_at or time.time())
            scheduled = fired.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if scheduled > fired:
                scheduled -= timedelta(days=1)
            # Se o PC estava desligado no horário, não despeja o resumo atrasado de manhã.
            if (fired - scheduled).total_seconds() < 2 * 3600:
                self.announce(str(self.day_summary()["message"]))
            # Mantém o próximo resumo no horário configurado, mesmo após um disparo atrasado.
            job.run_at = (scheduled + timedelta(days=1)).timestamp()
            self.scheduler._save(job)
            return

        late = (job.last_run_at or time.time()) - job.run_at
        text = f"Du, lembrete: {job.description}."
        if late > 300:
            text += f" Era para {datetime.fromtimestamp(job.run_at):%H:%M}; o Duque estava desligado."
        self.announce(text, urgent=True)

    def focus_active(self) -> bool:
        return self._focus_until is not None and time.time() < self._focus_until

    def focus_mode(self, action: str = "start", minutes: int | float = 25) -> dict[str, object]:
        value = action.casefold().strip()
        if value in {"stop", "parar", "sair", "encerrar", "off"}:
            if self._focus_timer:
                self._focus_timer.cancel()
            was_active = self.focus_active()
            self._focus_until, self._focus_timer = None, None
            return {"message": "Modo foco encerrado. Avisos de volta ao normal." if was_active else "O modo foco não estava ativo."}
        minutes = float(minutes)
        if not 1 <= minutes <= 240:
            return {"success": False, "error": "O foco precisa ter entre 1 e 240 minutos."}
        if self._focus_timer:
            self._focus_timer.cancel()
        paused = False
        try:
            if self.now_playing.get().get("playing"):
                self.assistant_tools.media("play_pause")
                self.now_playing.invalidate()
                paused = True
        except Exception:
            pass
        self._focus_until = time.time() + minutes * 60
        label = f"{minutes:g} minutos"

        def finish() -> None:
            self._focus_until, self._focus_timer = None, None
            self.announce(f"Du, fim dos {label} de foco. Hora de uma pausa.", urgent=True)

        self._focus_timer = threading.Timer(minutes * 60, finish)
        self._focus_timer.daemon = True
        self._focus_timer.start()
        return {
            "message": f"Modo foco por {label}." + (" Pausei a música." if paused else "") + " Seguro os avisos até lá.",
            "until": self._focus_until,
        }

    def _compose_text(self, prompt: str) -> str:
        """Texto criado pelo modelo para ferramentas (poema no Bloco de Notas...)."""
        return self.model.respond([{"role": "user", "content": prompt}]).text

    def _chat_response(self, text: str) -> str:
        """Responde usando a persona e o histórico compartilhado de texto e voz."""
        history = self.conversation.as_messages(16)
        if not history or history[-1]["role"] != "user" or history[-1]["content"] != text.strip():
            history.append({"role": "user", "content": text})
        response = self.model.respond([{"role": "system", "content": text_system_prompt(self.memory_digest())}, *history])
        return response.text.strip() or "Não consegui formular uma resposta agora."

    SMALL_TALK = frozenset({
        "oi", "ola", "olá", "e ai", "e aí", "eai", "fala", "salve", "opa", "hey",
        "bom dia", "boa tarde", "boa noite", "tudo bem", "tudo bom", "tudo certo", "beleza", "blz",
        "como vai", "como você está", "como voce esta", "como vai você", "como vai voce",
        "valeu", "vlw", "obrigado", "obrigada", "brigado", "muito obrigado", "tchau", "até mais", "ate mais",
        "boa", "show", "top", "ok", "certo", "entendi", "perfeito",
    })

    @classmethod
    def _is_small_talk(cls, text: str) -> bool:
        """Cumprimentos e respostas curtas vão direto para a conversa, sem ferramentas.

        Antes, "bom dia" passava pelo planejador do modelo, que às vezes
        respondia chamando a ferramenta de hora.
        """
        import re

        value = re.sub(r"\b(?:duque|jarvis|du)\b", " ", text.casefold())
        parts = [" ".join(re.sub(r"[^\wà-ú ]", " ", part).split()) for part in re.split(r"[,.!?;]+", value)]
        parts = [part for part in parts if part]
        return bool(parts) and all(part in cls.SMALL_TALK for part in parts)

    def _build_plan(self, text: str, intent: str):
        if intent in {"chat", "unknown"} and self._is_small_talk(text):
            return self.planner.build(text, "chat")
        # Ações operacionais simples devem ser determinísticas. O modelo fica
        # para tarefas ambíguas/complexas, evitando que um pedido claro vire "chat".
        if isinstance(self.model, NullModel) or intent in {"open_app", "close_app", "check_app", "file_operation", "system", "reminder", "open_search_result", "time", "weather", "media", "note", "calc", "shortcut"}:
            return self.planner.build(text, intent, set(self.schemas.names()), self._last_app)
        if intent in {"chat", "unknown"}:
            try:
                return self.model_planner.build(text, self.executor.tools.names(), context=self.conversation.transcript(6))
            except Exception:
                return self.planner.build(text, intent, context_app=self._last_app)
        try:
            return self.model_planner.build(text, self.executor.tools.names(), context=self.conversation.transcript(6))
        except Exception:
            return self.planner.build(text, intent, set(self.schemas.names()), self._last_app)

    def _validated_tool_steps(self, steps) -> list[tuple[str, dict[str, Any]]]:
        validated: list[tuple[str, dict[str, Any]]] = []
        for step in steps:
            tool = step.tool or ""
            arguments = step.arguments or {}
            if not tool:
                continue
            validation = self.schemas.validate(tool, arguments)
            if validation.valid:
                validated.append((tool, arguments))
        return validated

    def _ensure_executable_plan(self, text: str, intent: str, plan):
        tool_steps = self._validated_tool_steps(
            step for step in plan.steps if step.kind == StepKind.TOOL
        )
        if tool_steps:
            return tool_steps
        if intent in {"open_app", "close_app", "check_app", "search", "file_operation", "reminder", "system", "time", "weather", "media", "note", "calc", "shortcut"}:
            fallback = self.planner.build(text, intent, set(self.schemas.names()), self._last_app)
            return self._validated_tool_steps(
                step for step in fallback.steps if step.kind == StepKind.TOOL
            )
        return []

    def _autonomous_enabled(self) -> bool:
        return os.getenv("DUQUE_AUTONOMOUS_AGENT", "0").casefold() in {"1", "true", "yes", "on"} and not isinstance(self.model, NullModel)

    @staticmethod
    def _autonomous_requested(text: str) -> bool:
        value = " ".join(text.casefold().strip().split())
        markers = (
            "analise o projeto", "analisa o projeto", "analise o código", "analisa o código",
            "revise o projeto", "revisar o projeto", "investigue o projeto", "investiga o projeto",
            "verifique o projeto", "verifica o projeto", "melhore o projeto", "melhora o projeto",
            "corrija o projeto", "corrige o projeto", "encontre os problemas", "procure os problemas",
            "veja o que está errado", "veja o que esta errado", "trabalhe no projeto",
            "continue o projeto", "trabalhe nisso", "faça o que for necessário", "faca o que for necessario",
        )
        return any(marker in value for marker in markers)

    @staticmethod
    def _execution_message(value: object, fallback: str = "Tarefa concluída.") -> str:
        # O executor devolve ExecutionResult; a mensagem deve interpretar o
        # payload da ferramenta, não o envelope da execução.
        if isinstance(value, ExecutionResult):
            if not value.success:
                return value.error or fallback
            value = value.value
        if not isinstance(value, dict):
            return fallback
        if isinstance(value.get("message"), str) and value["message"].strip():
            return value["message"].strip()
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
        if value.get("opened") is True and "app" in value:
            return f"Abri o aplicativo {value.get('app', 'solicitado')}."
        if "closed" in value and "app" in value:
            if value.get("closed") is True:
                return f"Fechei o aplicativo {value.get('app', 'solicitado')}."
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
        if "workspace" in value and "file_count" in value:
            return f"Workspace: {value['workspace']}\nArquivos encontrados: {value['file_count']}."
        if "success" in value and "stdout" in value:
            return str(value.get("stdout") or value.get("stderr") or fallback).strip()
        return fallback

    def _handle_autonomous(self, text: str, *, confirmed: bool = False, task: Task | None = None) -> AgentResult:
        if task is None:
            task = self.tasks.create(text, mode="autonomous")
        context = AgentContext(goal=text, task_id=task.id)
        try:
            self.tasks.start(task.id)
            result = self.autonomous.run(context, confirmed=confirmed)
            if result.success:
                self.tasks.complete(task.id, result.message)
                self.memory.remember(MemoryLayer.OPERATIONAL, f"task:{task.id}", {"description": text, "status": "completed", "mode": "autonomous", "steps": result.steps})
                return AgentResult(result.message, task.id, result.executions[-1] if result.executions else None, result.steps or 1)
            if result.executions and result.executions[-1].confirmation_required:
                prompt = "Preciso da sua confirmação antes de executar essa ação."
                self.tasks.await_confirmation(task.id, prompt)
                self.tasks.set_confirmation_context(task.id, confirmation_intent="autonomous")
                self._pending_confirmation = PendingConfirmation(task.id, text, "autonomous", [])
                return AgentResult(prompt, task.id, result.executions[-1], result.steps or 1)
            if task.status.value == "running":
                self.tasks.fail(task.id, result.error or result.message or "Falha no agente autônomo")
            return AgentResult(result.message or f"Não consegui concluir a tarefa: {result.error}", task.id, result.executions[-1] if result.executions else None, result.steps or 1)
        except Exception as exc:
            if task.status.value == "running":
                self.tasks.fail(task.id, f"{type(exc).__name__}: {exc}")
            return AgentResult(f"O agente encontrou um erro: {type(exc).__name__}: {exc}", task.id)

    def _restore_pending_confirmation(self) -> None:
        """Recupera uma única confirmação pendente persistida antes de um reinício."""
        pending_tasks = [task for task in self.tasks.list() if task.status.value == "awaiting_confirmation"]
        if len(pending_tasks) != 1:
            return
        task = pending_tasks[0]
        metadata = task.metadata
        if metadata.get("mode") == "autonomous":
            self._pending_confirmation = PendingConfirmation(task.id, task.description, "autonomous", [])
            return
        raw_steps = metadata.get("confirmation_steps")
        intent = metadata.get("confirmation_intent")
        if not isinstance(intent, str) or not isinstance(raw_steps, list):
            return
        steps: list[tuple[str, dict[str, object]]] = []
        for item in raw_steps:
            if not isinstance(item, dict) or not isinstance(item.get("tool"), str) or not isinstance(item.get("arguments", {}), dict):
                return
            steps.append((item["tool"], item.get("arguments", {})))
        self._pending_confirmation = PendingConfirmation(task.id, task.description, intent, steps)

    @staticmethod
    def _is_confirmation(text: str) -> bool:
        normalized = " ".join(text.casefold().strip().split())
        return normalized in {
            "sim",
            "s",
            "confirmo",
            "confirmado",
            "confirmar",
            "pode",
            "pode fazer",
            "pode executar",
            "pode excluir",
            "pode apagar",
            "autorizo",
            "autorizado",
        }

    @staticmethod
    def _is_cancellation(text: str) -> bool:
        normalized = " ".join(text.casefold().strip().split())
        return normalized in {
            "não",
            "nao",
            "n",
            "cancela",
            "cancelar",
            "deixa",
            "deixa pra lá",
            "deixa pra la",
            "não pode",
            "nao pode",
        }

    def _resume_pending_confirmation(self, *, confirmed: bool, max_attempts: int) -> AgentResult:
        pending = self._pending_confirmation
        if pending is None:
            raise RuntimeError("Não há confirmação pendente")

        task = self.tasks.get(pending.task_id)
        if task is None:
            self._pending_confirmation = None
            return AgentResult("A ação pendente não está mais disponível para confirmação.")

        if pending.intent == "autonomous":
            self._pending_confirmation = None
            if not confirmed:
                self.tasks.cancel(task.id)
                self.memory.remember(
                    MemoryLayer.OPERATIONAL,
                    f"task:{task.id}",
                    {"description": pending.text, "status": "cancelled", "reason": "user_confirmation_denied"},
                )
                return AgentResult("Certo. Ação cancelada.", task.id)
            return self._handle_autonomous(pending.text, confirmed=True, task=task)

        if not confirmed:
            self.tasks.cancel(task.id)
            self._pending_confirmation = None
            self.memory.remember(
                MemoryLayer.OPERATIONAL,
                f"task:{task.id}",
                {"description": pending.text, "status": "cancelled", "reason": "user_confirmation_denied"},
            )
            return AgentResult("Certo. Ação cancelada.", task.id)

        self._pending_confirmation = None
        report = self.correction.run(
            task,
            lambda error, attempt: self._correct_steps(
                pending.text,
                pending.intent,
                pending.steps,
                error,
                attempt,
            ),
            max_attempts=max_attempts,
            confirmed=True,
        )
        if not report.success:
            failed = next((item.result for item in reversed(report.results) if not item.result.success), None)
            if failed and failed.confirmation_required:
                self._pending_confirmation = pending
                return AgentResult("A ação ainda exige confirmação antes de continuar.", task.id, failed, report.attempts)
            error = report.last_error or (failed.error if failed else "Falha desconhecida")
            self.memory.remember(
                MemoryLayer.OPERATIONAL,
                f"task:{task.id}",
                {"description": pending.text, "status": "failed", "error": error, "attempts": report.attempts},
            )
            return AgentResult(f"Não consegui executar a tarefa: {error}", task.id, failed, report.attempts)

        last = report.results[-1].result if report.results else None
        self.memory.remember(
            MemoryLayer.OPERATIONAL,
            f"task:{task.id}",
            {"description": pending.text, "status": "completed", "attempts": report.attempts},
        )
        return AgentResult(self._execution_message(last), task.id, last, report.attempts)

    def handle(
        self,
        text: str,
        *,
        confirmed: bool = False,
        max_attempts: int = 3,
        channel: str = "texto",
        record: bool = True,
    ) -> AgentResult:
        """Ponto de entrada único para texto e voz; registra a conversa compartilhada."""
        with self._handle_lock:
            if record:
                self.conversation.add("user", text, channel)
            result = self._handle(text, confirmed=confirmed, max_attempts=max_attempts)
            if record:
                self.conversation.add("assistant", result.text, channel)
            return result

    def _handle(self, text: str, *, confirmed: bool = False, max_attempts: int = 3) -> AgentResult:
        self.memory.remember(MemoryLayer.CONVERSATION, f"turn:{uuid4().hex}", {"role": "user", "text": text})
        if self._pending_confirmation is not None:
            if self._is_confirmation(text):
                return self._resume_pending_confirmation(confirmed=True, max_attempts=max_attempts)
            if self._is_cancellation(text):
                return self._resume_pending_confirmation(confirmed=False, max_attempts=max_attempts)
            pending = self._pending_confirmation
            return AgentResult(
                f"Tenho uma ação aguardando confirmação: {pending.text}. Responda 'confirmo' ou 'cancela'.",
                pending.task_id,
            )

        if self.forge_service is not None and self._forge_status_requested(text):
            return AgentResult(self._forge_status_text())

        if self.forge_service is not None and self._forge_requested(text):
            job = self.forge_service.submit(text)
            return AgentResult(
                "Coloquei na Forja. Vou trabalhar numa cópia isolada, testar e abrir o PR; "
                "se o CI passar, aplico e reinicio sozinho. "
                f"Trabalho {job['id']}, posição {job['position']} na fila."
            )

        # Pedidos em várias etapas ("abra o YouTube e toque X", "abra o Spotify e
        # aumente o volume"): cada etapa passa pelo fluxo completo, em ordem.
        steps = plan_steps(text) if not self._is_small_talk(text) else [text]
        if len(steps) > 1:
            return self._handle_sequence(steps, confirmed=confirmed, max_attempts=max_attempts)
        if steps and steps[0] and steps[0] != strip_name(text).strip(" ,.;"):
            text = steps[0]  # etapas unidas ("abra o YouTube e toque X" → "toque X no youtube")

        route = self.router.route(text, self._last_app)
        self.memory.remember(MemoryLayer.CONVERSATION, f"turn:{uuid4().hex}", {"role": "user", "text": text, "intent": route.intent.value})
        # Autonomia é uma capacidade disponível, não um modo obrigatório para toda mensagem.
        # Conversas simples devem responder normalmente; o loop autônomo entra quando o pedido
        # realmente solicita trabalho autônomo no projeto/sistema.
        if self._autonomous_enabled() and self._autonomous_requested(text):
            return self._handle_autonomous(text, confirmed=confirmed)
        task = self.tasks.create(text, intent=route.intent.value, confidence=route.confidence)

        # Mantém o último aplicativo citado para frases naturais como
        # "abre o Chrome" -> "ele está aberto?".
        plan = self._build_plan(text, route.intent.value)
        self.memory.remember(MemoryLayer.OPERATIONAL, f"task:{task.id}", {"description": text, "status": "created"})
        tool_steps = self._ensure_executable_plan(text, route.intent.value, plan)

        # Mesmo quando o roteador classifica uma mensagem como conversa ou desconhecida,
        # o modelo pode reconhecer que o pedido exige uma ferramenta (ex.: "abra o Chrome").
        # Só cai para a resposta conversacional quando nenhum passo executável foi planejado.
        if not tool_steps and route.intent.value in {"chat", "unknown"}:
            self.tasks.start(task.id)
            try:
                answer = self._chat_response(text)
            except Exception as exc:
                error = f"Não consegui gerar uma resposta: {type(exc).__name__}: {exc}"
                self.tasks.fail(task.id, error)
                self.memory.remember(
                    MemoryLayer.OPERATIONAL,
                    f"task:{task.id}",
                    {"description": text, "status": "failed", "error": error},
                )
                return AgentResult(error, task.id)
            self.tasks.complete(task.id, answer)
            self.memory.remember(
                MemoryLayer.OPERATIONAL,
                f"task:{task.id}",
                {"description": text, "status": "completed", "response": answer},
            )
            self.engine.emit(EventType.RESPONSE_STARTED, task_id=task.id)
            self.engine.emit(EventType.RESPONSE_FINISHED, task_id=task.id)
            return AgentResult(answer, task.id)
        if not tool_steps:
            self.tasks.start(task.id)
            if route.intent.value in {"open_app", "close_app", "check_app", "search", "file_operation", "reminder", "system", "open_search_result", "time", "weather", "media", "note", "calc", "shortcut"}:
                error = f"Nenhuma ferramenta disponível para a intenção: {route.intent.value}"
                self.tasks.fail(task.id, error)
                self.memory.remember(
                    MemoryLayer.OPERATIONAL,
                    f"task:{task.id}",
                    {"description": text, "status": "failed", "error": error},
                )
                self.engine.emit(EventType.TASK_FAILED, task_id=task.id, error=error)
                return AgentResult(f"Não consigo executar essa ação ainda: {error}.", task.id)
            self.tasks.complete(task.id, text)
            self.engine.emit(EventType.TASK_FINISHED, task_id=task.id)
            return AgentResult(text, task.id)
        report = self.correction.run(task, lambda error, attempt: self._correct_steps(text, route.intent.value, tool_steps, error, attempt), max_attempts=max_attempts, confirmed=confirmed)

        if report.success and route.intent.value in {"open_app", "close_app", "check_app"}:
            for tool_name, arguments in tool_steps:
                if tool_name in {"open_app", "close_app", "is_app_running"}:
                    app_name = arguments.get("name")
                    if isinstance(app_name, str) and app_name.strip():
                        self._last_app = app_name.strip()
                    break
        if not report.success:
            failed = next((item.result for item in reversed(report.results) if not item.result.success), None)
            if failed and failed.confirmation_required:
                self.tasks.set_confirmation_context(
                    task.id,
                    confirmation_intent=route.intent.value,
                    confirmation_steps=[
                        {"tool": tool, "arguments": arguments} for tool, arguments in tool_steps
                    ],
                )
                self._pending_confirmation = PendingConfirmation(task.id, text, route.intent.value, tool_steps)
                return AgentResult("Preciso da sua confirmação antes de executar essa ação.", task.id, failed, report.attempts)
            error = report.last_error or (failed.error if failed else "Falha desconhecida")
            self.memory.remember(MemoryLayer.OPERATIONAL, f"task:{task.id}", {"description": text, "status": "failed", "error": error, "attempts": report.attempts})
            return AgentResult(f"Não consegui executar a tarefa: {error}", task.id, failed, report.attempts)
        last = report.results[-1].result if report.results else None
        self.memory.remember(MemoryLayer.OPERATIONAL, f"task:{task.id}", {"description": text, "status": "completed", "attempts": report.attempts, "result": last.value if last is not None else None})
        return AgentResult(self._execution_message(last), task.id, last, report.attempts)

    def _handle_sequence(self, steps: list[str], *, confirmed: bool, max_attempts: int) -> AgentResult:
        """Executa as etapas em ordem; para na primeira que falhar e conta onde parou."""
        done: list[str] = []
        last: AgentResult | None = None
        for index, step in enumerate(steps, start=1):
            result = self._handle(step, confirmed=confirmed, max_attempts=max_attempts)
            last = result
            failed = result.execution is not None and not result.execution.success
            if self._pending_confirmation is not None:
                prefix = (" ".join(done) + " ") if done else ""
                return AgentResult(prefix + result.text, result.task_id, result.execution, result.attempts)
            if failed or result.text.startswith(("Não consegui", "Não consigo")):
                head = (" ".join(done) + " ") if done else ""
                rest = len(steps) - index
                tail = f" Parei aí; faltaram {rest} etapa(s)." if rest else ""
                return AgentResult(f"{head}Na etapa {index} ({step}): {result.text}{tail}".strip(), result.task_id, result.execution, result.attempts)
            done.append(result.text.strip().rstrip(".") + ".")
        assert last is not None
        return AgentResult(" ".join(done), last.task_id, last.execution, last.attempts)

    def _correct_steps(
        self,
        goal: str,
        intent: str,
        original_steps: list[tuple[str, dict[str, Any]]],
        error: str | None,
        attempt: int,
    ) -> list[tuple[str, dict[str, Any]]]:
        if not error:
            return original_steps

        correction_goal = (
            f"Objetivo original: {goal}\n"
            f"Falha da tentativa {attempt}: {error}\n"
            "Crie um novo plano corrigido."
        )
        try:
            if isinstance(self.model, NullModel):
                # O planner heurístico não possui contexto suficiente para reescrever
                # uma ação a partir de uma mensagem de erro; preserve a etapa original.
                return original_steps
            plan = self.model_planner.build(correction_goal, self.executor.tools.names())
            corrected = self._validated_tool_steps(
                step for step in plan.steps if step.kind == StepKind.TOOL
            )
            return corrected or original_steps
        except Exception:
            return original_steps
