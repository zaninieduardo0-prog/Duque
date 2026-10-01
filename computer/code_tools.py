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

    def run_python(self, path: str, timeout: int = 30) -> dict[str, Any]:
        target = self.workspace.resolve(path)
        if target.suffix.lower() != ".py":
            raise ValueError("run_python aceita apenas arquivos .py")
        completed = subprocess.run([sys.executable, str(target)], cwd=str(self.workspace.root), capture_output=True, text=True, timeout=max(1, min(timeout, 120)), shell=False)
        return {"path": str(target), "return_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr, "success": completed.returncode == 0}

    def run_tests(self, path: str = "tests", timeout: int = 120) -> dict[str, Any]:
        target = self.workspace.resolve(path)
        completed = subprocess.run([sys.executable, "-m", "pytest", str(target)], cwd=str(self.workspace.root), capture_output=True, text=True, timeout=max(1, min(timeout, 300)), shell=False)
        return {"target": str(target), "return_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr, "success": completed.returncode == 0}

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

    def git_log(self, limit: int = 10) -> dict[str, Any]:
        return self._git(["log", "--oneline", f"-{max(1, min(int(limit), 50))}"])

    def git_fetch(self) -> dict[str, Any]:
        return self._git(["fetch", "--all", "--prune"])

    def git_pull(self) -> dict[str, Any]:
        return self._git(["pull", "--ff-only"])

    def git_commit(self, message: str) -> dict[str, Any]:
        if not isinstance(message, str) or not message.strip():
            raise ValueError("message não pode ser vazio")
        add = self._git(["add", "-A"])
        if not add["success"]:
            return add
        return self._git(["commit", "-m", message.strip()])

    def git_push(self, remote: str = "origin", branch: str | None = None) -> dict[str, Any]:
        args = ["push", remote]
        if branch:
            args.append(branch)
        return self._git(args)

    def _git(self, args: list[str]) -> dict[str, Any]:
        completed = subprocess.run(["git", *args], cwd=str(self.workspace.root), capture_output=True, text=True, timeout=30, shell=False)
        return {"return_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr, "success": completed.returncode == 0}

    def register(self, executor: Any) -> None:
        executor.register("read_file", self.read_file)
        executor.register("write_file", self.write_file)
        executor.register("delete_file", self.delete_file)
        executor.register("list_files", self.list_files)
        executor.register("run_python", self.run_python)
        executor.register("run_tests", self.run_tests)
        executor.register("git_status", self.git_status)
        executor.register("git_diff", self.git_diff)
        executor.register("git_log", self.git_log)
        executor.register("git_fetch", self.git_fetch)
        executor.register("git_pull", self.git_pull)
        executor.register("git_commit", self.git_commit)
        executor.register("git_push", self.git_push)
