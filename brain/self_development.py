from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from computer.code_tools import CodeTools
from computer.workspace import Workspace


class SelfDevelopment:
    """Ferramentas controladas para o Duque analisar e desenvolver seu workspace."""

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self.tools = CodeTools(workspace)
        self.allow_changes = os.getenv("DUQUE_ALLOW_SELF_MODIFICATION", "0").casefold() in {"1", "true", "yes", "on"}

    def inspect(self) -> dict[str, Any]:
        files = self.workspace.list_files()
        python_files = [path for path in files if Path(path).suffix.lower() == ".py"]
        return {
            "workspace": str(self.workspace.root),
            "file_count": len(files),
            "python_files": python_files,
            "files": files,
            "self_modification_enabled": self.allow_changes,
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

    def apply_change(self, path: str, content: str) -> dict[str, Any]:
        if not self.allow_changes:
            return {
                "success": False,
                "error": "Auto-modificação desativada. Defina DUQUE_ALLOW_SELF_MODIFICATION=1 para permitir alterações.",
            }
        return self.tools.write_file(path, content)

    def register(self, executor: Any) -> None:
        executor.register("inspect_workspace", self.inspect)
        executor.register("read_many_files", self.read_many)
        # A ferramenta de auto-modificação só existe quando o modo foi explicitamente habilitado.
        if self.allow_changes:
            executor.register("apply_code_change", self.apply_change)
