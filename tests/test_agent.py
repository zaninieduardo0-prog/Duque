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


def test_agent_schema_registry_contains_only_registered_tools() -> None:
    agent = AgentLoop()
    registered = set(agent.executor.tools.names())
    assert set(agent.schemas.names()) <= registered
    assert "file_manager" not in agent.schemas.names()
    assert "scheduler" not in agent.schemas.names()
    assert "system_control" not in agent.schemas.names()


def test_schedule_task_is_registered_before_schema_catalog() -> None:
    agent = AgentLoop()
    assert "schedule_task" in agent.executor.tools.names()
    assert "schedule_task" in agent.schemas.names()


def test_planner_builds_read_file_operation() -> None:
    plan = Planner().build("leia o arquivo config.json", "file_operation", {"read_file"})
    assert plan.steps[0].tool == "read_file"
    assert plan.steps[0].arguments == {"path": "config.json"}


def test_planner_builds_delete_file_operation_only_when_available() -> None:
    plan = Planner().build("apague o arquivo lixo.txt", "file_operation", {"delete_file"})
    assert plan.steps[0].tool == "delete_file"
    assert plan.steps[0].arguments == {"path": "lixo.txt"}


def test_planner_builds_write_file_operation_from_natural_language() -> None:
    plan = Planner().build(
        "crie o arquivo teste.txt com conteúdo Olá Duque",
        "file_operation",
        {"write_file"},
    )
    assert plan.steps[0].tool == "write_file"
    assert plan.steps[0].arguments == {"path": "teste.txt", "content": "Olá Duque"}


def test_web_search_tool_is_registered() -> None:
    agent = AgentLoop()
    assert "web_search" in agent.executor.tools.names()
    assert "web_search" in agent.schemas.names()
