from __future__ import annotations

import re
import time
import unicodedata
from uuid import uuid4

from .config import ForgeConfig
from .git import Git, GitError
from .guard import FileChange


def slugify(text: str, limit: int = 40) -> str:
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized.casefold()).strip("-")
    return (slug[:limit].rstrip("-") or "tarefa")


class ForgeSandbox:
    """Cópia isolada do repositório (git worktree) num branch próprio.

    O agente só enxerga e altera este diretório; a instalação em execução
    continua intacta até o merge e a atualização controlada.
    """

    def __init__(self, config: ForgeConfig, goal: str) -> None:
        self.config = config
        self.goal = goal
        self.id = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:6]}"
        self.branch = f"{config.branch_prefix}{slugify(goal)}-{self.id[-6:]}"
        self.path = config.forge_dir / "work" / self.id
        self.repo = Git(config.repo_root)
        self.git = Git(self.path)
        self.base_ref = f"{config.remote}/{config.base_branch}"
        self.base_sha = ""
        self.created = False

    # ciclo de vida -----------------------------------------------------
    def create(self) -> ForgeSandbox:
        self.config.forge_dir.mkdir(parents=True, exist_ok=True)
        self.repo.run("fetch", self.config.remote, self.config.base_branch)
        self.base_sha = self.repo.out("rev-parse", self.base_ref)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.repo.run("worktree", "add", "-b", self.branch, str(self.path), self.base_sha)
        self.created = True
        return self

    def cleanup(self) -> None:
        if not self.created:
            return
        self.repo.run("worktree", "remove", "--force", str(self.path), check=False)
        self.repo.run("worktree", "prune", check=False)
        self.repo.run("branch", "-D", self.branch, check=False)
        self.created = False

    def __enter__(self) -> ForgeSandbox:
        return self.create()

    def __exit__(self, *_exc: object) -> None:
        self.cleanup()

    # inspeção ------------------------------------------------------------
    def changes(self) -> list[FileChange]:
        """Todas as alterações em relação ao main de origem (commitadas ou não)."""
        self.git.run("add", "-A")
        output = self.git.out("diff", "--cached", "--name-status", "--no-renames", self.base_sha)
        changes: list[FileChange] = []
        for line in output.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                changes.append(FileChange(parts[0], parts[-1]))
        return changes

    def diff(self, max_chars: int = 20000) -> str:
        self.git.run("add", "-A")
        text = self.git.run("diff", "--cached", "--stat", "--patch", self.base_sha).stdout
        if len(text) > max_chars:
            return text[:max_chars] + "\n...[diff truncado]"
        return text

    # publicação -----------------------------------------------------------
    def commit(self, message: str) -> str | None:
        self.git.run("add", "-A")
        if not self.git.run("diff", "--cached", "--quiet", check=False).code:
            return None
        self.git.run("commit", "-m", message, identity=True)
        return self.git.head()

    def push(self, *, force: bool = False) -> None:
        args = ["push", self.config.remote, f"HEAD:refs/heads/{self.branch}"]
        if force:
            args.insert(1, "--force")
        self.git.run(*args)

    def sync_with_base(self) -> bool:
        """Rebaseia sobre o main mais recente. Retorna True se precisou rebasear."""
        self.git.run("fetch", self.config.remote, self.config.base_branch)
        if self.git.is_ancestor(self.base_ref, "HEAD"):
            return False
        try:
            self.git.run("rebase", self.base_ref, identity=True)
        except GitError:
            self.git.run("rebase", "--abort", check=False)
            raise
        self.base_sha = self.git.out("rev-parse", self.base_ref)
        return True

    def merge_into_base(self) -> str:
        """Fast-forward do main remoto para este branch (nunca força)."""
        self.git.run("push", self.config.remote, f"HEAD:refs/heads/{self.config.base_branch}")
        return self.git.head()
