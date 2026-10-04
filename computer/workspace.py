from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Pasta do próprio TELEX (o código que está rodando agora).
PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Dados do TELEX (memória, configurações): podem mudar; o código, não.
_PROJECT_DATA = ("duque_data",)
# Pastas que não entram em listagens (ambiente virtual, Git, caches).
SKIP_DIRS = frozenset({".git", ".venv", "venv", "env", "__pycache__", "node_modules", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", "build", "dist"})


def self_modification_allowed() -> bool:
    return os.getenv("DUQUE_ALLOW_SELF_MODIFICATION", "0").casefold() in {"1", "true", "yes", "on"}


def is_project_source(path: str | Path, root: Path = PROJECT_ROOT) -> bool:
    """O caminho é parte do código do TELEX em execução (fora de duque_data)?

    Só a Forja muda o código: numa cópia isolada, com testes, PR e rollback.
    Uma ferramenta comum escrevendo aqui quebraria o TELEX sem volta.
    """
    target = Path(path).expanduser().resolve()
    try:
        relative = target.relative_to(root)
    except ValueError:
        return False
    return not (relative.parts and relative.parts[0] in _PROJECT_DATA)


def guard_project_source(path: str | Path, action: str = "alterar") -> None:
    if is_project_source(path) and not self_modification_allowed():
        raise PermissionError(
            f"Não posso {action} o código do próprio TELEX ({Path(path).name}). "
            "Peça à Forja (forge_improve): ela muda uma cópia isolada, testa e aplica com segurança."
        )


@dataclass(slots=True)
class FileResult:
    path: str
    content: str | None = None
    created: bool = False
    changed: bool = False


class Workspace:
    """Acesso a arquivos limitado a um diretório de trabalho explícito."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, relative_path: str | Path) -> Path:
        candidate = (self.root / relative_path).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise PermissionError("Caminho fora do workspace") from exc
        return candidate

    def _resolve(self, relative_path: str | Path) -> Path:
        return self.resolve(relative_path)

    def read(self, relative_path: str | Path) -> FileResult:
        path = self.resolve(relative_path)
        if not path.is_file():
            raise FileNotFoundError(str(path))
        return FileResult(str(path), path.read_text(encoding="utf-8"))

    def write(self, relative_path: str | Path, content: str) -> FileResult:
        path = self.resolve(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        existed = path.exists()
        old = path.read_text(encoding="utf-8") if existed and path.is_file() else None
        path.write_text(content, encoding="utf-8")
        return FileResult(str(path), created=not existed, changed=old != content)

    def delete(self, relative_path: str | Path) -> FileResult:
        path = self.resolve(relative_path)
        if not path.is_file():
            raise FileNotFoundError(str(path))
        path.unlink()
        return FileResult(str(path), changed=True)

    def list_files(self, limit: int = 5000) -> list[str]:
        """Arquivos do workspace, sem .git/.venv/caches (que travavam e enchiam o contexto)."""
        found: list[str] = []
        for current, dirs, files in os.walk(self.root):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.endswith(".egg-info"))
            base = Path(current)
            for name in sorted(files):
                found.append(str((base / name).relative_to(self.root)))
                if len(found) >= limit:
                    return sorted(found)
        return sorted(found)
