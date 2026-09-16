from __future__ import annotations

import json

from brain.agent_state import AgentContext
from brain.autonomous_loop import AutonomousLoop
from brain.model import ModelAdapter, ModelResponse
from brain.tool_schema import ToolSchemaRegistry, ToolSpec
from core.executor import Executor
from core.tasks import TaskManager


class FakeModel(ModelAdapter):
    def __init__(self, responses: list[object]) -> None:
        self.responses = iter(responses)
        self.messages: list[list[dict[str, str]]] = []

    def respond(self, messages, **kwargs):
        self.messages.append(list(messages))
        payload = next(self.responses)
        if isinstance(payload, str):
            return ModelResponse(text=payload)
        return ModelResponse(text=json.dumps(payload, ensure_ascii=False))


def make_loop(responses):
    tasks = TaskManager()
    executor = Executor(tasks=tasks)
    schemas = ToolSchemaRegistry()
    schemas.register(ToolSpec("echo", "Retorna o valor", ("value",), {"value": str}))
    executor.register("echo", lambda value: {"value": value})
    model = FakeModel(responses)
    loop = AutonomousLoop(model, executor, schemas, max_steps=5)
    task = tasks.create("teste")
    tasks.start(task.id)
    return loop, model, tasks, task


def test_autonomous_loop_feeds_tool_result_back_to_model():
    loop, model, tasks, task = make_loop([
        {"action": "tool", "tool": "echo", "arguments": {"value": "ok"}},
        {"action": "finish", "message": "Tudo certo."},
    ])
    result = loop.run(AgentContext("teste", task.id))
    assert result.success is True
    assert result.message == "Tudo certo."
    assert len(result.executions) == 1
    assert any("RESULTADO DA FERRAMENTA" in item["content"] for batch in model.messages for item in batch if item["role"] == "user")


def test_autonomous_loop_recovers_from_invalid_json():
    loop, model, tasks, task = make_loop([
        "isso não é json",
        {"action": "tool", "tool": "echo", "arguments": {"value": "ok"}},
        {"action": "finish", "message": "Recuperado."},
    ])
    context = AgentContext("teste", task.id)
    result = loop.run(context)
    assert result.success is True
    assert context.failures
    assert "JSON válido" in " ".join(context.failures)


def test_autonomous_loop_rejects_finish_without_evidence():
    loop, model, tasks, task = make_loop([
        {"action": "finish", "message": "Já fiz."},
        {"action": "tool", "tool": "echo", "arguments": {"value": "ok"}},
        {"action": "finish", "message": "Agora sim."},
    ])
    result = loop.run(AgentContext("teste", task.id))
    assert result.success is True
    assert result.message == "Agora sim."
    assert len(result.executions) == 1


def test_autonomous_loop_rejects_unknown_tool():
    loop, tasks_model, tasks, task = make_loop([
        {"action": "tool", "tool": "nao_existe", "arguments": {}},
    ])
    result = loop.run(AgentContext("teste", task.id))
    assert result.success is False
    assert result.error == "Limite de 5 passos atingido"
