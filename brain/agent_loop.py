from __future__ import annotations

import os
from dataclasses import dataclass
from uuid import uuid4

from automation.runner import ScheduledTaskRunner
from automation.scheduler import Scheduler
from core.engine import DuqueEngine
from core.events import EventType
from core.executor import ExecutionResult, Executor
from core.task_engine import TaskEngine
from core.tasks import TaskManager
from computer.code_tools import CodeTools
from computer.runtime import create_ui_tools, create_verification
from computer.screen_tools import ScreenTools
from computer.tools import ComputerTools
from computer.ui_tools import UITools
from computer.verification_tools import VerificationTools
from computer.verified_ui import VerifiedScreenActions
from computer.visual_workflow import VisualWorkflow
from computer.workspace import Workspace
from memory.memory import Memory, MemoryLayer
from .agent_state import AgentContext
from .autonomous_loop import AutonomousLoop
from .model import ModelAdapter, NullModel
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


@dataclass(slots=True)
class PendingAutonomousConfirmation:
    task_id: str
    text: str
    tool: str
    arguments: dict[str, object]


class AgentLoop:
    """Orquestra entendimento, planejamento, execução, verificação, correção, memória e agenda."""

    def __init__(self, engine: DuqueEngine | None = None, tasks: TaskManager | None = None, executor: Executor | None = None, workspace: Workspace | None = None, ui_tools: UITools | None = None, model: ModelAdapter | None = None, model_planner: ModelPlanner | None = None, memory: Memory | None = None) -> None:
        self.engine = engine or DuqueEngine()
        self.router = IntentRouter()
        self.planner = Planner()
        self.tasks = tasks or TaskManager()
        self.verification = create_verification()
        self.executor = executor or Executor(self.tasks, verification=self.verification, event_sink=self.engine.emit)
        self.workspace = workspace or Workspace(os.getenv("DUQUE_WORKSPACE", "duque_workspace"))
        ComputerTools().register(self.executor)
        CodeTools(self.workspace).register(self.executor)
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
        self.model = model or NullModel()
        self.schemas = ToolSchemaRegistry()
        self.executor.register("schedule_task", self._schedule_task)
        self._register_tool_schemas()
        self.model_planner = model_planner or ModelPlanner(self.model, self.schemas)
        self.autonomous = AutonomousLoop(self.model, self.executor, self.schemas, observer=self._observe_screen, event_sink=self.engine.emit)
        self.memory = memory or Memory()
        self._pending_confirmation: PendingConfirmation | None = None
        self._pending_autonomous_confirmation: PendingAutonomousConfirmation | None = None

        self.scheduler = Scheduler(database=self.tasks.database)
        self.scheduled_runner = ScheduledTaskRunner(self.scheduler, self.task_engine, self.tasks, event_sink=self.engine.emit)
        self.scheduled_runner.start()

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
            ToolSpec("open_url", "Abre uma URL no navegador; pode ser usada para serviços web como WhatsApp Web", ("url",), {"url": str}),
            ToolSpec("open_path", "Abre um caminho existente", ("path",), {"path": str}),
            ToolSpec("web_search", "Pesquisa na web", ("query",), {"query": str}),
            ToolSpec("read_file", "Lê um arquivo do workspace", ("path",), {"path": str}),
            ToolSpec("read_many_files", "Lê vários arquivos do workspace", ("paths",), {"paths": list}),
            ToolSpec("write_file", "Escreve arquivo no workspace", ("path", "content"), {"path": str, "content": str}),
            ToolSpec("delete_file", "Exclui um arquivo do workspace", ("path",), {"path": str}),
            ToolSpec("apply_code_change", "Aplica uma alteração de código somente quando a auto-modificação estiver explicitamente habilitada", ("path", "content"), {"path": str, "content": str}),
            ToolSpec("list_files", "Lista arquivos do workspace"),
            ToolSpec("inspect_workspace", "Inspeciona a estrutura do workspace"),
            ToolSpec("run_python", "Executa Python no workspace", ("path",), {"path": str}),
            ToolSpec("git_status", "Consulta o estado do repositório Git sem alterar arquivos"),
            ToolSpec("git_diff", "Consulta diferenças locais do repositório Git", (), {"path": str}),
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

    def _build_plan(self, text: str, intent: str):
        if isinstance(self.model, NullModel):
            return self.planner.build(text, intent, set(self.schemas.names()))
        if intent in {"chat", "unknown"}:
            return self.planner.build(text, intent)
        try:
            return self.model_planner.build(text, self.executor.tools.names())
        except Exception:
            return self.planner.build(text, intent)

    def _validated_tool_steps(self, steps):
        validated: list[tuple[str, dict[str, object]]] = []
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
        if intent in {"open_app", "search", "file_operation", "reminder", "system"}:
            fallback = self.planner.build(text, intent, set(self.schemas.names()))
            return self._validated_tool_steps(
                step for step in fallback.steps if step.kind == StepKind.TOOL
            )
        return []

    def autonomous_enabled(self) -> bool:
        return os.getenv("DUQUE_AUTONOMOUS_AGENT", "0").casefold() in {"1", "true", "yes", "on"} and not isinstance(self.model, NullModel)

    def _autonomous_enabled(self) -> bool:
        return self.autonomous_enabled()

    def _handle_autonomous(
        self,
        text: str,
        *,
        confirmed: bool = False,
        task_id: str | None = None,
        confirmed_action: tuple[str, dict[str, object]] | None = None,
    ) -> AgentResult:
        task = self.tasks.get(task_id) if task_id else None
        if task is None:
            task = self.tasks.create(text, mode="autonomous")
        context = AgentContext(goal=text, task_id=task.id)
        try:
            self.tasks.start(task.id)
            result = self.autonomous.run(context, confirmed_action=confirmed_action if confirmed else None)
            if result.success:
                self.tasks.complete(task.id, result.message)
                self.memory.remember(MemoryLayer.OPERATIONAL, f"task:{task.id}", {"description": text, "status": "completed", "mode": "autonomous", "steps": result.steps})
                return AgentResult(result.message, task.id, result.executions[-1] if result.executions else None, result.steps or 1)
            if result.error and result.error.startswith("Ação '") and "exige confirmação" in result.error:
                prompt = "Preciso da sua confirmação antes de continuar essa ação."
                self.tasks.await_confirmation(task.id, prompt)
                self._pending_autonomous_confirmation = PendingAutonomousConfirmation(
                    task.id,
                    text,
                    result.pending_tool or "",
                    result.pending_arguments or {},
                )
                return AgentResult(prompt, task.id, result.executions[-1] if result.executions else None, result.steps or 1)
            if task.status.value == "running":
                self.tasks.fail(task.id, result.error or result.message or "Falha no agente autônomo")
            return AgentResult(result.message or f"Não consegui concluir a tarefa: {result.error}", task.id, result.executions[-1] if result.executions else None, result.steps or 1)
        except Exception as exc:
            if task.status.value == "running":
                self.tasks.fail(task.id, f"{type(exc).__name__}: {exc}")
            return AgentResult(f"O agente encontrou um erro: {type(exc).__name__}: {exc}", task.id)

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
        return AgentResult("Tarefa concluída.", task.id, last, report.attempts)

    def handle(self, text: str, *, confirmed: bool = False, max_attempts: int = 3) -> AgentResult:
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

        if self._pending_autonomous_confirmation is not None:
            pending = self._pending_autonomous_confirmation
            if self._is_cancellation(text):
                task = self.tasks.get(pending.task_id)
                if task is not None:
                    self.tasks.cancel(task.id)
                self._pending_autonomous_confirmation = None
                self.memory.remember(
                    MemoryLayer.OPERATIONAL,
                    f"task:{pending.task_id}",
                    {"description": pending.text, "status": "cancelled", "reason": "user_confirmation_denied"},
                )
                return AgentResult("Certo. Ação cancelada.", pending.task_id)
            if self._is_confirmation(text):
                self._pending_autonomous_confirmation = None
                return self._handle_autonomous(
                    pending.text,
                    confirmed=True,
                    task_id=pending.task_id,
                    confirmed_action=(pending.tool, pending.arguments),
                )
            return AgentResult(
                f"Tenho uma ação aguardando confirmação: {pending.text}. Responda 'confirmo' ou 'cancela'.",
                pending.task_id,
            )

        route = self.router.route(text)
        self.memory.remember(MemoryLayer.CONVERSATION, f"turn:{uuid4().hex}", {"role": "user", "text": text, "intent": route.intent.value})
        if self._autonomous_enabled():
            return self._handle_autonomous(text, confirmed=confirmed)
        plan = self._build_plan(text, route.intent.value)
        task = self.tasks.create(text, intent=route.intent.value, confidence=route.confidence)
        self.memory.remember(MemoryLayer.OPERATIONAL, f"task:{task.id}", {"description": text, "status": "created"})
        tool_steps = self._ensure_executable_plan(text, route.intent.value, plan)
        if not tool_steps:
            self.tasks.start(task.id)
            if route.intent.value in {"open_app", "search", "file_operation", "reminder", "system"}:
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
        if not report.success:
            failed = next((item.result for item in reversed(report.results) if not item.result.success), None)
            if failed and failed.confirmation_required:
                self._pending_confirmation = PendingConfirmation(task.id, text, route.intent.value, tool_steps)
                return AgentResult("Preciso da sua confirmação antes de executar essa ação.", task.id, failed, report.attempts)
            error = report.last_error or (failed.error if failed else "Falha desconhecida")
            self.memory.remember(MemoryLayer.OPERATIONAL, f"task:{task.id}", {"description": text, "status": "failed", "error": error, "attempts": report.attempts})
            return AgentResult(f"Não consegui executar a tarefa: {error}", task.id, failed, report.attempts)
        last = report.results[-1].result if report.results else None
        self.memory.remember(MemoryLayer.OPERATIONAL, f"task:{task.id}", {"description": text, "status": "completed", "attempts": report.attempts})
        return AgentResult("Tarefa concluída.", task.id, last, report.attempts)

    def _correct_steps(self, goal: str, intent: str, original_steps, error: str | None, attempt: int):
        if not error:
            return original_steps

        correction_goal = (
            f"Objetivo original: {goal}\\n"
            f"Falha da tentativa {attempt}: {error}\\n"
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
