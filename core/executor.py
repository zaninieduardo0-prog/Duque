from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .security import SecurityPolicy
from .tasks import TaskManager, Task


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
    """Executa planos através de ferramentas registradas e política de segurança."""

    def __init__(self, tasks: TaskManager | None = None, security: SecurityPolicy | None = None) -> None:
        self.tasks = tasks or TaskManager()
        self.security = security or SecurityPolicy()
        self.tools = ToolRegistry()

    def register(self, name: str, tool: Tool) -> None:
        self.tools.register(name, tool)

    def execute(self, task: Task, tool_name: str, arguments: dict[str, Any] | None = None, *, confirmed: bool = False) -> ExecutionResult:
        policy = self.security.assess(tool_name)
        if policy.confirmation_required and not confirmed:
            return ExecutionResult(False, confirmation_required=True, error=f"Ação '{tool_name}' exige confirmação")

        tool = self.tools.get(tool_name)
        if tool is None:
            self.tasks.fail(task.id, f"Ferramenta não registrada: {tool_name}")
            return ExecutionResult(False, error=f"Ferramenta não registrada: {tool_name}")

        self.tasks.start(task.id)
        try:
            value = tool(**(arguments or {}))
            self.tasks.complete(task.id, value)
            return ExecutionResult(True, value=value)
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            self.tasks.fail(task.id, message)
            return ExecutionResult(False, error=message)
