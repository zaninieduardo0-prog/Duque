from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.engine import DuqueEngine
from core.events import EventType
from core.executor import ExecutionResult, Executor
from core.tasks import TaskManager
from .planner import Planner
from .router import IntentRouter


@dataclass(slots=True)
class AgentResult:
    text: str
    task_id: str | None = None
    execution: ExecutionResult | None = None


class AgentLoop:
    """Orquestra entendimento -> plano -> execução sem depender da voz."""

    def __init__(self, engine: DuqueEngine | None = None) -> None:
        self.engine = engine or DuqueEngine()
        self.router = IntentRouter()
        self.planner = Planner()
        self.tasks = TaskManager()
        self.executor = Executor(self.tasks)

    def handle(self, text: str) -> AgentResult:
        route = self.router.route(text)
        plan = self.planner.build(text, route.intent.value)
        task = self.tasks.create(text, intent=route.intent.value, confidence=route.confidence)

        self.engine.emit(EventType.TASK_STARTED, task_id=task.id, description=text)

        for step in plan.steps:
            if step.kind.value != "tool":
                continue
            result = self.executor.execute(task, step.tool or "", step.arguments)
            if result.confirmation_required:
                self.engine.emit(EventType.TASK_FAILED, task_id=task.id, reason="confirmation_required")
                return AgentResult("Preciso da sua confirmação antes de executar essa ação.", task.id, result)
            if not result.success:
                self.engine.emit(EventType.TASK_FAILED, task_id=task.id, error=result.error)
                return AgentResult(f"Não consegui executar a tarefa: {result.error}", task.id, result)

        self.engine.emit(EventType.TASK_FINISHED, task_id=task.id)
        if route.intent.value == "chat":
            return AgentResult(text, task.id)
        return AgentResult("Tarefa processada.", task.id)
