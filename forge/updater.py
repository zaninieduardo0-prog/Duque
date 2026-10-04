from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .git import Git, GitError
from .quality import QualityGate

RESTART_EXIT_CODE = 75


@dataclass(slots=True)
class UpdateResult:
    status: str  # up_to_date | updated | refused | rolled_back | failed
    message: str
    previous: str | None = None
    current: str | None = None


def read_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def write_state(path: Path, **data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state = read_state(path)
    state.update(data, updated_at=time.time())
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


class Updater:
    """Atualiza a instalação em execução a partir do main remoto.

    Só avança por fast-forward, nunca descarta alterações locais do usuário,
    valida a nova versão antes de pedir reinício e volta à anterior se a
    validação falhar. O supervisor cuida do rollback se o Duque não subir.
    """

    def __init__(
        self,
        repo_root: str | Path,
        *,
        remote: str = "origin",
        base_branch: str = "main",
        smoke: QualityGate | None = None,
        state_path: str | Path | None = None,
    ) -> None:
        self.root = Path(repo_root)
        self.git = Git(self.root)
        self.remote = remote
        self.base = base_branch
        self.smoke = smoke or QualityGate(("compile", "pytest"))
        self.state_path = Path(state_path) if state_path else self.root / "duque_data" / "update_state.json"

    def apply(self) -> UpdateResult:
        try:
            branch = self.git.current_branch()
            if branch != self.base:
                return UpdateResult("refused", f"instalação está no branch '{branch}', não em '{self.base}'")
            dirty = self.git.dirty_tracked_files()
            if dirty:
                return UpdateResult("refused", "há alterações locais não commitadas: " + ", ".join(dirty[:10]))

            self.git.run("fetch", self.remote, self.base)
            previous = self.git.head()
            target = self.git.out("rev-parse", f"{self.remote}/{self.base}")
            if previous == target:
                return UpdateResult("up_to_date", "já está na versão mais recente", previous, previous)
            if not self.git.is_ancestor(previous, target):
                return UpdateResult("refused", "a instalação tem commits locais que não estão no remoto", previous, target)
            if target == self.state().get("failed"):
                return UpdateResult("refused", f"a versão {target[:10]} já falhou antes; aguardando uma correção", previous, target)

            self.git.run("merge", "--ff-only", target)
            gate = self.smoke.run(self.root)
            if not gate.passed:
                dirty = self.git.dirty_tracked_files()
                if dirty:
                    # A validação alterou arquivos versionados: reset --hard apagaria isso.
                    write_state(self.state_path, status="rollback_refused", previous=previous, current=target, failed=target, dirty=dirty[:20])
                    return UpdateResult("failed", "nova versão falhou na validação e há arquivos alterados; não voltei sozinho: " + ", ".join(dirty[:10]), previous, target)
                self.git.run("reset", "--hard", previous)
                write_state(self.state_path, status="rolled_back", previous=previous, current=previous, failed=target, reason=gate.failure_report(2000))
                return UpdateResult("rolled_back", f"nova versão falhou na validação ({gate.summary()}); voltei para a anterior", previous, previous)

            write_state(self.state_path, status="updated", previous=previous, current=target)
            return UpdateResult("updated", f"atualizado de {previous[:10]} para {target[:10]}", previous, target)
        except GitError as exc:
            return UpdateResult("failed", str(exc))

    def mark_pending_restart(self, result: UpdateResult) -> None:
        """Só quando o reinício vai mesmo acontecer: o supervisor observa a versão nova."""
        write_state(self.state_path, status="pending_restart", previous=result.previous, current=result.current)

    def state(self) -> dict[str, Any]:
        return read_state(self.state_path)

    def as_dict(self, result: UpdateResult) -> dict[str, Any]:
        return asdict(result)
