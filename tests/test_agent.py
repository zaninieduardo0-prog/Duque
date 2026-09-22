from brain.agent import BrainAgent
from brain.model import NullModel
from brain.agent_loop import AgentLoop


def test_null_model_round_trip() -> None:
    brain = BrainAgent(NullModel())
    result = brain.respond("teste")
    assert result.text == "teste"


def test_agent_loop_chat_does_not_require_voice_or_api() -> None:
    result = AgentLoop().handle("olá Duque")
    assert result.task_id
    assert result.text == "olá Duque"


def test_agent_loop_open_app_uses_registered_tool() -> None:
    agent = AgentLoop()
    agent.executor.tools._tools["open_app"] = lambda name: {"opened": name}
    result = agent.handle("abrir o bloco de notas")
    assert result.task_id
    assert result.execution is not None
    assert result.execution.success
    assert result.execution.value == {"opened": "bloco de notas"}
