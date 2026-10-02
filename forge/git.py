from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

# Identidade usada nos commits feitos pela Forja; não depende da configuração
# global do Git do usuário.
FORGE_IDENTITY = ("-c", "user.name=Duque Forja", "-c", "user.email=duque-forja@users.noreply.github.com")


class GitError(RuntimeError):
    def __init__(self, args: list[str], result: GitResult) -> None:
        detail = (result.stderr or result.stdout).strip()
        super().__init__(f"git {' '.join(args)} falhou ({result.code}): {detail[-800:]}")
        self.result = result


@dataclass(slots=True, frozen=True)
class GitResult:
    code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.code == 0


class Git:
    """Executa comandos git em um diretório, sem shell."""

    def __init__(self, cwd: str | Path, timeout: int = 180) -> None:
        self.cwd = Path(cwd)
        self.timeout = timeout

    def run(self, *args: str, check: bool = True, identity: bool = False) -> GitResult:
        command = ["git", *(FORGE_IDENTITY if identity else ()), *args]
        completed = subprocess.run(
            command,
            cwd=str(self.cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.timeout,
            shell=False,
        )
        result = GitResult(completed.returncode, completed.stdout, completed.stderr)
        if check and not result.ok:
            raise GitError(list(args), result)
        return result

    def out(self, *args: str) -> str:
        return self.run(*args).stdout.strip()

    def head(self) -> str:
        return self.out("rev-parse", "HEAD")

    def current_branch(self) -> str:
        return self.out("rev-parse", "--abbrev-ref", "HEAD")

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        return self.run("merge-base", "--is-ancestor", ancestor, descendant, check=False).ok

    def dirty_tracked_files(self) -> list[str]:
        """Arquivos versionados com alteração local (ignora não versionados)."""
        output = self.out("status", "--porcelain", "--untracked-files=no")
        return [line[3:] for line in output.splitlines() if line.strip()]

    def remote_url(self, remote: str = "origin") -> str:
        return self.out("remote", "get-url", remote)
