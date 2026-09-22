from brain.agent import BrainAgent
from brain.agent_loop import AgentLoop
from brain.model import NullModel
from brain.planner import Planner
from brain.router import Intent, IntentRouter


def test_null_model_round_trip() -> None:
    brain = BrainAgent(NullModel())
    result = brain.respond("teste")
    assert result.text == "teste"


def test_agent_loop_chat_does_not_require_voice_or_api() -> None:
    result = AgentLoop().handle("olá Duque")
    assert result.task_id
    assert result.text == "olá Duque"


def test_router_classifies_open_app_request() -> None:
    route = IntentRouter().route("abrir o bloco de notas")
    assert route.intent is Intent.OPEN_APP


def test_planner_extracts_application_name() -> None:
    plan = Planner().build("abrir o bloco de notas", "open_app")
    assert len(plan.steps) == 1
    assert plan.steps[0].tool == "open_app"
    assert plan.steps[0].arguments == {"name": "bloco de notas"}


def test_agent_loop_open_app_uses_registered_tool() -> None:
    agent = AgentLoop()
    agent.executor.tools._tools["open_app"] = lambda name: {"opened": name}
    result = agent.handle("abrir o bloco de notas")
    assert result.task_id
    assert result.execution is not None
    assert result.execution.success
    assert result.execution.value == {"opened": "bloco de notas"}


def test_agent_loop_correction_uses_heuristic_planner_without_model() -> None:
    agent = AgentLoop(model=NullModel())
    steps = agent._correct_steps(
        "abrir o bloco de notas",
        "open_app",
        [("open_app", {"name": "bloco de notas"})],
        "falha simulada",
        2,
    )
    assert steps == [("open_app", {"name": "bloco de notas"})]


def test_agent_loop_rejects_invalid_planned_arguments() -> None:
    agent = AgentLoop()
    plan = agent.planner.build("abrir o bloco de notas", "open_app")
    plan.steps[0].arguments["inventado"] = "x"
    assert agent._ensure_executable_plan("abrir o bloco de notas", "open_app", plan) == [
        ("open_app", {"name": "bloco de notas"})
    ]


def test_planner_does_not_invent_unregistered_tools() -> None:
    plan = Planner().build("pesquisar o preço do dólar", "search", {"open_app"})
    assert plan.steps == []


def test_agent_loop_does_not_complete_unsupported_operational_intent() -> None:
    agent = AgentLoop()
    result = agent.handle("pesquisar o preço do dólar")
    assert result.task_id
    assert "Não consigo executar essa ação ainda" in result.text
    task = agent.tasks.get(result.task_id)
    assert task is not None
    assert task.status.value == "failed"
