from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from computer.code_tools import CodeTools
from computer.workspace import Workspace


@dataclass(slots=True)
class DevelopmentReport:
    goal: str
    inspected_files: list[str] = field(default_factory=list)
    tests_run: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    changes: list[dict[str, Any]] = field(default_factory=list)
    success: bool = False


class SelfDevelopment:
    """Ferramentas controladas para o Duque analisar e testar seu workspace."""

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self.tools = CodeTools(workspace)
        self.allow_changes = os.getenv("DUQUE_ALLOW_SELF_MODIFICATION", "1").casefold() in {"1", "true", "yes", "on"}

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

    def run_tests(self, path: str = "tests") -> dict[str, Any]:
        target = self.workspace.resolve(path)
        if target.is_dir():
            import subprocess
            import sys
            completed = subprocess.run(
                [sys.executable, "-m", "pytest", str(target)],
                cwd=str(self.workspace.root), capture_output=True, text=True, timeout=120, shell=False,
            )
            return {
                "target": str(target),
                "return_code": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "success": completed.returncode == 0,
            }
        return self.tools.run_python(path)

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
        executor.register("run_tests", self.run_tests)
        executor.register("apply_code_change", self.apply_change)
