from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from .workspace import Workspace


class CodeTools:
    """Ferramentas de programação sem shell livre."""

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    def read_file(self, path: str) -> dict[str, Any]:
        result = self.workspace.read(path)
        return {"path": result.path, "content": result.content}

    def write_file(self, path: str, content: str) -> dict[str, Any]:
        result = self.workspace.write(path, content)
        return {"path": result.path, "created": result.created, "changed": result.changed}

    def list_files(self) -> dict[str, Any]:
        return {"files": self.workspace.list_files()}

    def run_python(self, path: str, timeout: int = 30) -> dict[str, Any]:
        target = self.workspace._resolve(path)
        if target.suffix.lower() != ".py":
            raise ValueError("run_python aceita apenas arquivos .py")
        completed = subprocess.run(
            [sys.executable, str(target)],
            cwd=str(self.workspace.root),
            capture_output=True,
            text=True,
            timeout=max(1, min(timeout, 120)),
            shell=False,
        )
        return {
            "path": str(target),
            "return_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "success": completed.returncode == 0,
        }

    def register(self, executor: Any) -> None:
        executor.register("read_file", self.read_file)
        executor.register("write_file", self.write_file)
        executor.register("list_files", self.list_files)
        executor.register("run_python", self.run_python)
