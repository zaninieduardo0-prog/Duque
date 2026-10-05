from brain.natural_language_patch import _natural_file_plan
from brain.planner import Planner, StepKind


def test_glued_du_prefix_routes_desktop_file_request() -> None:
    goal = 'Ducrie um arquivo chamado teste.txt na área de trabalho contendo "123"'
    plan = _natural_file_plan(Planner(), goal, {"write_desktop_file"})
    assert plan is not None
    assert len(plan.steps) == 1
    step = plan.steps[0]
    assert step.kind == StepKind.TOOL
    assert step.tool == "write_desktop_file"
    assert step.arguments == {"filename": "teste.txt", "content": "123"}
