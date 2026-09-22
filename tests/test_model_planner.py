from __future__ import annotations

import json

import pytest

from brain.model import ModelAdapter, ModelResponse
from brain.model_planner import ModelPlanner
from brain.tool_schema import ToolSchemaRegistry, ToolSpec


class FakeModel(ModelAdapter):
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.messages = []

    def respond(self, messages, **kwargs):
        self.messages.append(messages)
        if isinstance(self.payload, str):
            return ModelResponse(text=self.payload)
        return ModelResponse(text=json.dumps(self.payload, ensure_ascii=False))


def make_planner(payload: object) -> tuple[ModelPlanner, FakeModel]:
    schemas = ToolSchemaRegistry()
    schemas.register(ToolSpec("echo", "Retorna valor", ("value",), {"value": str}))
    model = FakeModel(payload)
    return ModelPlanner(model, schemas), model


def test_model_planner_exposes_tool_schemas_to_model() -> None:
    planner, model = make_planner({"goal": "teste", "steps": []})
    planner.build("teste")
    prompt = model.messages[0][1]["content"]
    assert "echo" in prompt
    assert "value" in prompt


def test_model_planner_rejects_unavailable_tool() -> None:
    planner, _ = make_planner({"goal": "teste", "steps": [{"description": "x", "kind": "tool", "tool": "shell", "arguments": {}}]})
    with pytest.raises(ValueError, match="não disponível"):
        planner.build("teste")


def test_model_planner_accepts_fenced_json() -> None:
    planner, _ = make_planner('```json\n{"goal":"teste","steps":[]}\n```')
    plan = planner.build("teste")
    assert plan.goal == "teste"


def test_model_planner_rejects_invalid_steps_shape() -> None:
    planner, _ = make_planner({"goal": "teste", "steps": {}})
    with pytest.raises(ValueError, match="steps deve ser uma lista"):
        planner.build("teste")
