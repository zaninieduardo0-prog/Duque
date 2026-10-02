from __future__ import annotations

import subprocess
import sys
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

    def run_tests(self, path: str = ".", timeout: int = 120) -> dict[str, Any]:
        """Valida o workspace sem depender de uma pasta tests."""
        target = self.workspace.resolve(path)
        tests_dir = self.workspace.root / "tests"
        if tests_dir.is_dir():
            command = [sys.executable, "-m", "pytest", str(tests_dir)]
            target_label = "tests"
        else:
            command = [
                sys.executable,
                "-m",
                "compileall",
                "-q",
                str(target),
            ]
            target_label = str(target)
        completed = subprocess.run(
            command,
            cwd=str(self.workspace.root),
            capture_output=True,
            text=True,
            timeout=max(1, min(timeout, 300)),
            shell=False,
        )
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
        add = self._git(["add", "-A"])
        if not add["success"]:
            return add
        return self._git(["commit", "-m", message.strip()])

    def git_push(self, remote: str = "origin", branch: str | None = None) -> dict[str, Any]:
        args = ["push", remote]
        if branch:
            args.append(branch)
        return self._git(args)

    def propose_change(self, path: str, content: str, branch: str | None = None, message: str | None = None) -> dict[str, Any]:
        """Cria uma branch, aplica a alteração no arquivo, cria um commit e volta para a branch original.

        Retorna: {branch, commit, diff, success, error}
        """
        import uuid
        # validações básicas
        if not isinstance(path, str) or not isinstance(content, str):
            return {"success": False, "error": "path e content devem ser strings"}

        original_branch_proc = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(self.workspace.root), capture_output=True, text=True, shell=False)
        if original_branch_proc.returncode != 0:
            return {"success": False, "error": "Não foi possível detectar branch atual", "stderr": original_branch_proc.stderr}
        original_branch = original_branch_proc.stdout.strip()

        branch_name = branch or f"duque/autogen/{uuid.uuid4().hex[:8]}"
        commit_msg = (message or f"Duque: proposta de alteração em {path}").strip()

        try:
            # cria branch
            r = self._git(["checkout", "-b", branch_name])
            if not r["success"]:
                return {"success": False, "error": "Falha ao criar branch", "details": r}

            # escreve arquivo
            self.workspace.write(path, content)

            # adiciona e comita
            add = self._git(["add", "-A"])
            if not add["success"]:
                raise RuntimeError(f"git add falhou: {add.get('stderr')}" )
            commit = self._git(["commit", "-m", commit_msg])
            if not commit["success"]:
                # pode ser que não haja mudanças; ainda assim tentamos obter diff
                pass

            # obter hash do commit (HEAD)
            rev = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=str(self.workspace.root), capture_output=True, text=True, shell=False)
            commit_hash = rev.stdout.strip() if rev.returncode == 0 else None

            # diff entre branch e original
            diff_proc = subprocess.run(["git", "diff", f"{original_branch}..{branch_name}", "--", path], cwd=str(self.workspace.root), capture_output=True, text=True, shell=False)
            diff_text = diff_proc.stdout if diff_proc.returncode == 0 else ""

            result = {
                "success": True,
                "branch": branch_name,
                "commit": commit_hash,
                "base_branch": original_branch,
                "diff": diff_text,
            }
            return result
        except Exception as exc:
            return {"success": False, "error": str(exc)}
        finally:
            # volta para a branch original para não alterar o ambiente de trabalho do usuário
            self._git(["checkout", original_branch])

    def _git(self, args: list[str]) -> dict[str, Any]:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(self.workspace.root),
            capture_output=True,
            text=True,
            timeout=30,
            shell=False,
        )
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
        executor.register("propose_change", self.propose_change)
        executor.register("merge_branch", self.merge_branch)

    def merge_branch(self, branch: str, target: str | None = None) -> dict[str, Any]:
        """Faz merge da branch especificada para a target (ou branch atual se target None)."""
        tgt = target
        if tgt is None:
            # determina branch atual
            proc = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(self.workspace.root), capture_output=True, text=True, shell=False)
            if proc.returncode != 0:
                return {"success": False, "error": "Não foi possível detectar branch atual", "stderr": proc.stderr}
            tgt = proc.stdout.strip()

        # executa merge
        res = self._git(["merge", "--no-ff", branch])
        return res
