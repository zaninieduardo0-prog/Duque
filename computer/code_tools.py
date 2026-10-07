from __future__ import annotations

import os
import subprocess
from typing import Any

from core.windows import console_python

from ._proc import run_quiet
from .workspace import Workspace, guard_project_source

# Operações que falam com o remoto podem demorar mais que as locais.
_NETWORK_GIT = {"push", "fetch", "pull"}
MAX_READ_BYTES = 2_000_000


def _failed(error: str, **extra: Any) -> dict[str, Any]:
    return {"return_code": None, "stdout": extra.pop("stdout", ""), "stderr": extra.pop("stderr", ""), "success": False, "error": error, **extra}


class CodeTools:
    """Ferramentas de programação controladas, sem shell arbitrário."""

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    def read_file(self, path: str) -> dict[str, Any]:
        target = self.workspace.resolve(path)
        if target.is_file() and target.stat().st_size > MAX_READ_BYTES:
            raise ValueError(f"Arquivo grande demais para ler inteiro ({target.stat().st_size} bytes); use read_any_file com max_bytes.")
        result = self.workspace.read(path)
        return {"path": result.path, "content": result.content}

    def write_file(self, path: str, content: str) -> dict[str, Any]:
        guard_project_source(self.workspace.resolve(path), "alterar")
        result = self.workspace.write(path, content)
        return {"path": result.path, "created": result.created, "changed": result.changed}

    def delete_file(self, path: str) -> dict[str, Any]:
        guard_project_source(self.workspace.resolve(path), "apagar")
        result = self.workspace.delete(path)
        return {"path": result.path, "deleted": True}

    def list_files(self) -> dict[str, Any]:
        return {"files": self.workspace.list_files()}

    def run_python(self, path: str, timeout: int = 30) -> dict[str, Any]:
        target = self.workspace.resolve(path)
        if target.suffix.lower() != ".py":
            raise ValueError("run_python aceita apenas arquivos .py")
        limit = max(1, min(int(timeout), 120))
        try:
            completed = run_quiet([console_python(), str(target)], cwd=str(self.workspace.root), timeout=limit, encoding="utf-8")
        except subprocess.TimeoutExpired as exc:
            return _failed(f"O script passou de {limit}s e foi encerrado.", path=str(target), stdout=exc.output or "", stderr=exc.stderr or "", timed_out=True)
        return {
            "path": str(target),
            "return_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "success": completed.returncode == 0,
        }

    def run_tests(self, path: str = ".", timeout: int = 120) -> dict[str, Any]:
        """Valida o workspace sem depender de uma pasta tests."""
        target = self.workspace.resolve(path)
        tests_dir = self.workspace.root / "tests"
        if tests_dir.is_dir():
            command = [console_python(), "-m", "pytest", str(tests_dir)]
            target_label = "tests"
        else:
            command = [
                console_python(),
                "-m",
                "compileall",
                "-q",
                str(target),
            ]
            target_label = str(target)
        limit = max(1, min(int(timeout), 300))
        try:
            completed = run_quiet(command, cwd=str(self.workspace.root), timeout=limit, encoding="utf-8")
        except subprocess.TimeoutExpired:
            return _failed(f"Os testes passaram de {limit}s e foram encerrados.", target=target_label, timed_out=True)
        return {
            "target": target_label,
            "return_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "success": completed.returncode == 0,
        }

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
        # Só arquivos já rastreados: "add -A" versionava segredos e lixo novos por engano.
        add = self._git(["add", "-u"])
        if not add["success"]:
            return add
        return self._git(["commit", "-m", message.strip()])

    def git_push(self, remote: str = "origin", branch: str | None = None) -> dict[str, Any]:
        for value in (remote, branch):
            if value is not None and (not isinstance(value, str) or not value.strip() or value.strip().startswith("-")):
                raise ValueError(f"Nome de remoto/branch inválido: {value!r}")
        args = ["push", remote.strip()]
        if branch:
            args.append(branch.strip())
        return self._git(args)

    def _git(self, args: list[str]) -> dict[str, Any]:
        # Sem prompts de credencial: um git esperando senha travava o agente (e a
        # janela de login do Git Credential Manager aparecia do nada).
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never", GIT_ASKPASS="", SSH_ASKPASS="")
        limit = 120 if args and args[0] in _NETWORK_GIT else 30
        try:
            completed = run_quiet(["git", *args], cwd=str(self.workspace.root), timeout=limit, encoding="utf-8", env=env)
        except subprocess.TimeoutExpired:
            return _failed(f"git {args[0] if args else ''} passou de {limit}s e foi encerrado.", timed_out=True)
        except OSError as exc:
            return _failed(f"git indisponível: {exc}")
        return {
            "return_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "success": completed.returncode == 0,
        }

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
