from __future__ import annotations

from dataclasses import dataclass

from core.engine import DuqueEngine
from core.events import EventType
from core.executor import ExecutionResult, Executor
from core.tasks import TaskManager
from computer.tools import ComputerTools
from .planner import Planner
from .router import IntentRouter


@dataclass(slots=True)
class AgentResult:
    text: str
    task_id: str | None = None
    execution: ExecutionResult | None = None


class AgentLoop:
    """Orquestra entendimento -> plano -> execução sem depender da voz."""

    def __init__(
        self,
        engine: DuqueEngine | None = None,
        tasks: TaskManager | None = None,
        executor: Executor | None = None,
    ) -> None:
        self.engine = engine or DuqueEngine()
        self.router = IntentRouter()
        self.planner = Planner()
        self.tasks = tasks or TaskManager()
        self.executor = executor or Executor(self.tasks)
        ComputerTools().register(self.executor)

    def handle(self, text: str, *, confirmed: bool = False) -> AgentResult:
        route = self.router.route(text)
        plan = self.planner.build(text, route.intent.value)
        task = self.tasks.create(text, intent=route.intent.value, confidence=route.confidence)

        self.engine.emit(EventType.TASK_STARTED, task_id=task.id, description=text)

        tool_steps = [
            (step.tool or "", step.arguments)
            for step in plan.steps
            if step.kind.value == "tool" and step.tool
        ]

        if not tool_steps:
            self.tasks.complete(task.id, text)
            self.engine.emit(EventType.TASK_FINISHED, task_id=task.id)
            return AgentResult(text, task.id)

        results = self.executor.execute_task(task, tool_steps, confirmed=confirmed)
        failed = next((result for result in results if not result.success), None)

        if failed:
            self.engine.emit(EventType.TASK_FAILED, task_id=task.id, error=failed.error)
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

        self.engine.emit(EventType.TASK_FINISHED, task_id=task.id)
        values = [result.value for result in results]
        return AgentResult("Tarefa concluída.", task.id, results[-1] if results else None)
