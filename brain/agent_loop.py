from __future__ import annotations

from dataclasses import dataclass

from core.engine import DuqueEngine
from core.events import EventType
from core.executor import ExecutionResult, Executor
from core.task_engine import TaskEngine
from core.tasks import TaskManager
from computer.code_tools import CodeTools
from computer.runtime import create_ui_tools
from computer.tools import ComputerTools
from computer.ui_tools import UITools
from computer.workspace import Workspace
from .model import ModelAdapter, NullModel
from .model_planner import ModelPlanner
from .planner import Planner, StepKind
from .router import IntentRouter
from .self_correction import SelfCorrection
from .tool_schema import ToolSchemaRegistry, ToolSpec


@dataclass(slots=True)
class AgentResult:
    text: str
    task_id: str | None = None
    execution: ExecutionResult | None = None
    attempts: int = 1


class AgentLoop:
    """Orquestra entendimento, planejamento, execução e correção sem depender da voz."""

    def __init__(
        self,
        engine: DuqueEngine | None = None,
        tasks: TaskManager | None = None,
        executor: Executor | None = None,
        workspace: Workspace | None = None,
        ui_tools: UITools | None = None,
        model: ModelAdapter | None = None,
        model_planner: ModelPlanner | None = None,
    ) -> None:
        self.engine = engine or DuqueEngine()
        self.router = IntentRouter()
        self.planner = Planner()
        self.tasks = tasks or TaskManager()
        self.executor = executor or Executor(self.tasks)
        self.workspace = workspace or Workspace("duque_workspace")
        ComputerTools().register(self.executor)
        CodeTools(self.workspace).register(self.executor)
        (ui_tools or create_ui_tools()).register(self.executor)
        self.task_engine = TaskEngine(self.executor, self.tasks, self.engine.emit)
        self.correction = SelfCorrection(self.task_engine)
        self.model = model or NullModel()
        self.schemas = ToolSchemaRegistry()
        self._register_tool_schemas()
        self.model_planner = model_planner or ModelPlanner(self.model, self.schemas)

    def _register_tool_schemas(self) -> None:
        specs = [
            ToolSpec("open_app", "Abre um aplicativo", ("name",), {"name": str}),
            ToolSpec("open_url", "Abre uma URL", ("url",), {"url": str}),
            ToolSpec("open_path", "Abre um caminho existente", ("path",), {"path": str}),
            ToolSpec("web_search", "Pesquisa na web", ("query",), {"query": str}),
            ToolSpec("read_file", "Lê um arquivo do workspace", ("path",), {"path": str}),
            ToolSpec("write_file", "Escreve arquivo no workspace", ("path", "content"), {"path": str, "content": str}),
            ToolSpec("list_files", "Lista arquivos do workspace"),
            ToolSpec("run_python", "Executa Python no workspace", ("path",), {"path": str}),
            ToolSpec("ui_click", "Clica na tela", ("x", "y"), {"x": int, "y": int}),
            ToolSpec("ui_type_text", "Digita texto", ("text",), {"text": str}),
            ToolSpec("ui_press", "Pressiona uma tecla", ("key",), {"key": str}),
            ToolSpec("ui_hotkey", "Pressiona combinação de teclas", ("keys",), {"keys": list}),
            ToolSpec("screenshot", "Captura a tela"),
        ]
        for spec in specs:
            self.schemas.register(spec)

    def _build_plan(self, text: str, intent: str):
        if intent in {"chat", "unknown"}:
            return self.planner.build(text, intent)
        try:
            return self.model_planner.build(text, self.executor.tools.names())
        except Exception:
            return self.planner.build(text, intent)

    def handle(self, text: str, *, confirmed: bool = False, max_attempts: int = 3) -> AgentResult:
        route = self.router.route(text)
        plan = self._build_plan(text, route.intent.value)
        task = self.tasks.create(text, intent=route.intent.value, confidence=route.confidence)

        tool_steps = [
            (step.tool or "", step.arguments)
            for step in plan.steps
            if step.kind == StepKind.TOOL and step.tool
        ]

        if not tool_steps:
            self.tasks.complete(task.id, text)
            self.engine.emit(EventType.TASK_FINISHED, task_id=task.id)
            return AgentResult(text, task.id)

        report = self.correction.run(
            task,
            lambda error, attempt: self._correct_steps(text, route.intent.value, tool_steps, error, attempt),
            max_attempts=max_attempts,
            confirmed=confirmed,
        )

        if not report.success:
            failed = next((item.result for item in reversed(report.results) if not item.result.success), None)
            if failed and failed.confirmation_required:
                return AgentResult("Preciso da sua confirmação antes de executar essa ação.", task.id, failed, report.attempts)
            error = report.last_error or (failed.error if failed else "Falha desconhecida")
            return AgentResult(f"Não consegui executar a tarefa: {error}", task.id, failed, report.attempts)

        last = report.results[-1].result if report.results else None
        return AgentResult("Tarefa concluída.", task.id, last, report.attempts)

    def _correct_steps(self, goal: str, intent: str, original_steps, error: str | None, attempt: int):
        if not error:
            return original_steps
        try:
            plan = self.model_planner.build(
                f"Objetivo original: {goal}\nFalha da tentativa {attempt}: {error}\nCrie um novo plano corrigido.",
                self.executor.tools.names(),
            )
            return [(step.tool, step.arguments) for step in plan.steps if step.kind == StepKind.TOOL and step.tool]
        except Exception:
            return original_steps
