from __future__ import annotations

import json

from brain.agent_state import AgentContext
from brain.autonomous_loop import AutonomousLoop
from brain.model import ModelAdapter, ModelResponse
from brain.tool_schema import ToolSchemaRegistry, ToolSpec
from core.executor import Executor
from core.tasks import TaskManager


class FakeModel(ModelAdapter):
    def __init__(self, responses: list[dict]) -> None:
        self.responses = iter(responses)

    def respond(self, messages, **kwargs):
        return ModelResponse(text=json.dumps(next(self.responses), ensure_ascii=False))


def make_loop(responses):
    tasks = TaskManager()
    executor = Executor(tasks=tasks)
    schemas = ToolSchemaRegistry()
    schemas.register(ToolSpec("echo", "Retorna o valor", ("value",), {"value": str}))
    executor.register("echo", lambda value: {"value": value})
    loop = AutonomousLoop(FakeModel(responses), executor, schemas, max_steps=5)
    task = tasks.create("teste")
    tasks.start(task.id)
    return loop, tasks, task


def test_autonomous_loop_feeds_tool_result_back_to_model():
    loop, tasks, task = make_loop([
        {"action": "tool", "tool": "echo", "arguments": {"value": "ok"}},
        {"action": "finish", "message": "Tudo certo."},
    ])
    result = loop.run(AgentContext("teste", task.id))
    assert result.success is True
    assert result.message == "Tudo certo."
    assert len(result.executions) == 1


def test_autonomous_loop_rejects_unknown_tool():
    loop, tasks, task = make_loop([
        {"action": "tool", "tool": "nao_existe", "arguments": {}},
    ])
    result = loop.run(AgentContext("teste", task.id))
    assert result.success is False
    assert result.error == "Limite de 5 passos atingido"


def test_schema_registry_exposes_names_and_descriptions():
    schemas = ToolSchemaRegistry()
    schemas.register(ToolSpec("zeta", "Z", (), {}))
    schemas.register(ToolSpec("alpha", "A", (), {}))
    assert schemas.names() == ["alpha", "zeta"]
    assert {item["name"] for item in schemas.describe()} == {"alpha", "zeta"}
