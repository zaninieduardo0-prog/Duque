from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .security import SecurityPolicy
from .tasks import Task, TaskManager

Tool = Callable[..., Any]


@dataclass(slots=True)
class ExecutionResult:
    success: bool
    value: Any = None
    error: str | None = None
    confirmation_required: bool = False


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
    """Executa ferramentas e normaliza falhas declaradas pelo próprio tool."""

    def __init__(self, tasks: TaskManager | None = None, security: SecurityPolicy | None = None) -> None:
        self.tasks = tasks or TaskManager()
        self.security = security or SecurityPolicy()
        self.tools = ToolRegistry()

    def register(self, name: str, tool: Tool) -> None:
        self.tools.register(name, tool)

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
            return ExecutionResult(False, error=f"Ação '{tool_name}' exige confirmação", confirmation_required=True)

        tool = self.tools.get(tool_name)
        if tool is None:
            return ExecutionResult(False, error=f"Ferramenta não registrada: {tool_name}")

        if manage_task:
            self.tasks.start(task.id)
        try:
            value = tool(**(arguments or {}))
            if isinstance(value, dict) and value.get("success") is False:
                error = value.get("error") or value.get("stderr") or f"Ferramenta '{tool_name}' reportou falha"
                return ExecutionResult(False, value=value, error=str(error))
            return ExecutionResult(True, value=value)
        except Exception as exc:
            return ExecutionResult(False, error=f"{type(exc).__name__}: {exc}")

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
                self.tasks.fail(task.id, result.error or "Falha na execução")
                return results

        self.tasks.complete(task.id, [result.value for result in results])
        return results
