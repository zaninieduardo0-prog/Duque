from __future__ import annotations

from pathlib import Path
from typing import Any

from computer.code_tools import CodeTools
from computer.workspace import Workspace


class SelfDevelopment:
    """Ferramentas para o Duque analisar seu workspace.

    Alterar o próprio código é papel exclusivo da Forja (veja FORJA.md).
    """

    def __init__(self, workspace: Workspace, tools: CodeTools | None = None) -> None:
        self.workspace = workspace
        self.tools = tools or CodeTools(workspace)

    def inspect(self) -> dict[str, Any]:
        files = self.workspace.list_files()
        python_files = [path for path in files if Path(path).suffix.lower() == ".py"]
        return {
            "workspace": str(self.workspace.root),
            "file_count": len(files),
            "python_files": python_files,
        }

    def read_many(self, paths: list[str]) -> dict[str, Any]:
        if not isinstance(paths, list):
            raise ValueError("paths deve ser uma lista")
        result: dict[str, Any] = {}
        for path in paths:
            if not isinstance(path, str):
                raise ValueError("Cada caminho deve ser texto")
            result[path] = self.tools.read_file(path)["content"]
        return result

    def register(self, executor: Any) -> None:
        executor.register("inspect_workspace", self.inspect)
        executor.register("read_many_files", self.read_many)
