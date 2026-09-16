from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .events import EventType
from .security import SecurityPolicy
from .tasks import Task, TaskManager

Tool = Callable[..., Any]


@dataclass(slots=True)
class ExecutionResult:
    success: bool
    value: Any = None
    error: str | None = None
    confirmation_required: bool = False
    verification: Any = None


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, name: str, tool: Tool) -> None:
        if not name.strip():
            raise ValueError("Nome da ferramenta não pode ser vazio")
        self._tools[name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)


class Executor:
    """Executa ferramentas e, quando configurado, verifica ações externas."""

    DEFAULT_VERIFIED_TOOLS = frozenset({
        "ui_click",
        "ui_type_text",
        "ui_press",
        "ui_hotkey",
    })

    def __init__(
        self,
        tasks: TaskManager | None = None,
        security: SecurityPolicy | None = None,
        verification: Any | None = None,
        verified_tools: set[str] | frozenset[str] | None = None,
        event_sink: Callable[..., Any] | None = None,
    ) -> None:
        self.tasks = tasks or TaskManager()
        self.security = security or SecurityPolicy()
        self.tools = ToolRegistry()
        self.verification = verification
        self.verified_tools = frozenset(verified_tools or self.DEFAULT_VERIFIED_TOOLS)
        self.event_sink = event_sink

    def register(self, name: str, tool: Tool) -> None:
        self.tools.register(name, tool)

    def _emit(self, event: EventType, **data: Any) -> None:
        if self.event_sink:
            self.event_sink(event, **data)

    def execute_step(
        self,
        task: Task,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        confirmed: bool = False,
        manage_task: bool = True,
    ) -> ExecutionResult:
        policy = self.security.assess(tool_name)
        if policy.confirmation_required and not confirmed:
            return ExecutionResult(
                False,
                error=f"Ação '{tool_name}' exige confirmação",
                confirmation_required=True,
            )

        tool = self.tools.get(tool_name)
        if tool is None:
            return ExecutionResult(False, error=f"Ferramenta não registrada: {tool_name}")

        if manage_task:
            self.tasks.start(task.id)

        before = None
        if self.verification is not None and tool_name in self.verified_tools:
            self._emit(EventType.OBSERVATION_STARTED, task_id=task.id, tool=tool_name, phase="before")
            before = self.verification.snapshot()
            self._emit(EventType.OBSERVATION_FINISHED, task_id=task.id, tool=tool_name, phase="before")

        try:
            value = tool(**(arguments or {}))
        except Exception as exc:
            return ExecutionResult(False, error=f"{type(exc).__name__}: {exc}")

        verification = None
        if before is not None:
            self._emit(EventType.VERIFICATION_STARTED, task_id=task.id, tool=tool_name)
            verification = self.verification.verify_change(before)
            self._emit(
                EventType.VERIFICATION_FINISHED,
                task_id=task.id,
                tool=tool_name,
                status=verification.status.value,
                changed=verification.changed,
                confidence=verification.confidence,
            )
            if not verification.changed:
                return ExecutionResult(
                    False,
                    value=value,
                    error=f"Ação executada, mas a verificação não detectou mudança: {verification.reason}",
                    verification=verification,
                )

        return ExecutionResult(True, value=value, verification=verification)

    def execute_task(
        self,
        task: Task,
        steps: list[tuple[str, dict[str, Any] | None]],
        *,
        confirmed: bool = False,
    ) -> list[ExecutionResult]:
        self.tasks.start(task.id)
        results: list[ExecutionResult] = []

        for tool_name, arguments in steps:
            result = self.execute_step(task, tool_name, arguments, confirmed=confirmed, manage_task=False)
            results.append(result)
            if not result.success:
                if result.confirmation_required:
                    self.tasks.fail(task.id, result.error or "Confirmação necessária")
                else:
                    self.tasks.fail(task.id, result.error or "Falha na execução")
                return results

        self.tasks.complete(task.id, [result.value for result in results])
        return results
