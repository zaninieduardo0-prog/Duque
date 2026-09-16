from __future__ import annotations

from dataclasses import dataclass

from core.engine import DuqueEngine
from core.events import EventType
from core.executor import ExecutionResult, Executor
from core.task_engine import TaskEngine
from core.tasks import TaskManager
from computer.tools import ComputerTools
from computer.workspace import Workspace
from computer.code_tools import CodeTools
from .planner import Planner
from .router import IntentRouter


@dataclass(slots=True)
class AgentResult:
    text: str
    task_id: str | None = None
    execution: ExecutionResult | None = None


class AgentLoop:
    """Orquestra entendimento, planejamento e execução sem depender da voz."""

    def __init__(
        self,
        engine: DuqueEngine | None = None,
        tasks: TaskManager | None = None,
        executor: Executor | None = None,
        workspace: Workspace | None = None,
    ) -> None:
        self.engine = engine or DuqueEngine()
        self.router = IntentRouter()
        self.planner = Planner()
        self.tasks = tasks or TaskManager()
        self.executor = executor or Executor(self.tasks)
        self.workspace = workspace or Workspace("duque_workspace")
        ComputerTools().register(self.executor)
        CodeTools(self.workspace).register(self.executor)
        self.task_engine = TaskEngine(self.executor, self.tasks, self.engine.emit)

    def handle(self, text: str, *, confirmed: bool = False) -> AgentResult:
        route = self.router.route(text)
        plan = self.planner.build(text, route.intent.value)
        task = self.tasks.create(text, intent=route.intent.value, confidence=route.confidence)

        tool_steps = [
            (step.tool or "", step.arguments)
            for step in plan.steps
            if step.kind.value == "tool" and step.tool
        ]

        if not tool_steps:
            self.tasks.complete(task.id, text)
            self.engine.emit(EventType.TASK_FINISHED, task_id=task.id)
            return AgentResult(text, task.id)

        results = self.task_engine.run(task, tool_steps, confirmed=confirmed)
        failed = next((item.result for item in results if not item.result.success), None)

        if failed:
            if failed.confirmation_required:
                return AgentResult(
                    "Preciso da sua confirmação antes de executar essa ação.",
                    task.id,
                    failed,
                )
            return AgentResult(
                f"Não consegui executar a tarefa: {failed.error}",
                task.id,
                failed,
            )

        last = results[-1].result if results else None
        return AgentResult("Tarefa concluída.", task.id, last)
