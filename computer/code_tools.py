from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from .workspace import Workspace


class CodeTools:
    """Ferramentas de programação controladas, sem shell arbitrário."""

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    def read_file(self, path: str) -> dict[str, Any]:
        result = self.workspace.read(path)
        return {"path": result.path, "content": result.content}

    def write_file(self, path: str, content: str) -> dict[str, Any]:
        result = self.workspace.write(path, content)
        return {"path": result.path, "created": result.created, "changed": result.changed}

    def delete_file(self, path: str) -> dict[str, Any]:
        result = self.workspace.delete(path)
        return {"path": result.path, "deleted": True}

    def list_files(self) -> dict[str, Any]:
        return {"files": self.workspace.list_files()}

    def inspect_workspace(self) -> dict[str, Any]:
        """Retorna uma visão curta e segura da estrutura do workspace."""
        root = self.workspace.root
        directories = sorted(
            str(path.relative_to(root))
            for path in root.rglob("*")
            if path.is_dir()
        )
        files = self.workspace.list_files()
        return {
            "root": str(root),
            "directories": directories,
            "files": files,
            "file_count": len(files),
            "directory_count": len(directories),
        }

    def validate_python(self, path: str) -> dict[str, Any]:
        target = self.workspace.resolve(path)
        if target.suffix.lower() != ".py":
            raise ValueError("validate_python aceita apenas arquivos .py")
        try:
            source = target.read_text(encoding="utf-8")
            compile(source, str(target), "exec")
            return {"path": str(target), "valid": True, "success": True, "error": None}
        except SyntaxError as exc:
            return {
                "path": str(target),
                "valid": False,
                "success": False,
                "error": f"{exc.msg} (linha {exc.lineno}, coluna {exc.offset})",
            }

    def run_python(self, path: str, timeout: int = 30) -> dict[str, Any]:
        target = self.workspace.resolve(path)
        if target.suffix.lower() != ".py":
            raise ValueError("run_python aceita apenas arquivos .py")
        completed = subprocess.run([sys.executable, str(target)], cwd=str(self.workspace.root), capture_output=True, text=True, timeout=max(1, min(timeout, 120)), shell=False)
        return {"path": str(target), "return_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr, "success": completed.returncode == 0}

    def git_status(self) -> dict[str, Any]:
        return self._git(["status", "--short", "--branch"])

    def git_diff(self, path: str | None = None) -> dict[str, Any]:
        args = ["diff", "--"]
        if path:
            self.workspace.resolve(path)
            args.append(path)
        result = self._git(args)
        result["path"] = path
        return result

    def _git(self, args: list[str]) -> dict[str, Any]:
        completed = subprocess.run(["git", *args], cwd=str(self.workspace.root), capture_output=True, text=True, timeout=30, shell=False)
        return {"return_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr, "success": completed.returncode == 0}

    def register(self, executor: Any) -> None:
        executor.register("read_file", self.read_file)
        executor.register("write_file", self.write_file)
        executor.register("delete_file", self.delete_file)
        executor.register("list_files", self.list_files)
        executor.register("inspect_workspace", self.inspect_workspace)
        executor.register("validate_python", self.validate_python)
        executor.register("run_python", self.run_python)
        executor.register("git_status", self.git_status)
        executor.register("git_diff", self.git_diff)
