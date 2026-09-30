from pathlib import Path

from computer.code_tools import CodeTools
from computer.workspace import Workspace


class DummyExecutor:
    def __init__(self):
        self.tools = {}

    def register(self, name, tool):
        self.tools[name] = tool


def test_inspect_workspace_reports_files_and_directories(tmp_path: Path):
    (tmp_path / "agent").mkdir()
    (tmp_path / "agent" / "duque.py").write_text("print('ok')", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Duque", encoding="utf-8")

    result = CodeTools(Workspace(tmp_path)).inspect_workspace()

    assert result["root"] == str(tmp_path.resolve())
    assert "agent" in result["directories"]
    assert "agent/duque.py" in result["files"]
    assert "README.md" in result["files"]
    assert result["file_count"] == 2
    assert result["directory_count"] == 1


def test_code_tools_registers_workspace_inspection(tmp_path: Path):
    executor = DummyExecutor()
    CodeTools(Workspace(tmp_path)).register(executor)

    assert "inspect_workspace" in executor.tools
