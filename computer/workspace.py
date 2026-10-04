from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Pastas que nunca entram na listagem: histórico do Git, ambientes, caches e dados.
SKIPPED_DIRS = frozenset({
    ".git", ".venv", "venv", "__pycache__", "node_modules",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "duque_data",
})
MAX_LISTED_FILES = 2000

# Código-fonte do próprio Duque: alterá-lo é trabalho exclusivo da Forja, que
# roda numa cópia isolada e passa por portão de qualidade antes do merge.
PROTECTED_SOURCE_DIRS = frozenset({
    "core", "brain", "computer", "forge", "memory", "automation",
    "voice", "agent", "interface", ".github",
})


@dataclass(slots=True)
class FileResult:
    path: str
    content: str | None = None
    created: bool = False
    changed: bool = False


def is_duque_project(root: Path) -> bool:
    return (root / "duque.py").is_file() and (root / "forge").is_dir()


def encode_text(content: str) -> bytes:
    """Bytes que ``write_text`` gravaria (UTF-8, quebra de linha nativa)."""
    if os.linesep != "\n":
        content = content.replace("\n", os.linesep)
    return content.encode("utf-8")


class Workspace:
    """Acesso a arquivos limitado a um diretório de trabalho explícito.

    ``allow_self_modification`` só deve ser ligado pela Forja, que trabalha
    numa cópia isolada do projeto.
    """

    def __init__(self, root: str | Path, *, allow_self_modification: bool = False) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.protects_self = not allow_self_modification and is_duque_project(self.root)

    def resolve(self, relative_path: str | Path) -> Path:
        candidate = (self.root / relative_path).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise PermissionError("Caminho fora do workspace") from exc
        return candidate

    def _resolve_writable(self, relative_path: str | Path) -> Path:
        path = self.resolve(relative_path)
        parts = path.relative_to(self.root).parts
        if not parts:
            raise PermissionError("Não é possível alterar a raiz do workspace")
        if ".git" in parts:
            raise PermissionError("Alterar arquivos internos do Git não é permitido")
        if any(part == ".env" or part.startswith(".env.") for part in parts):
            raise PermissionError("Alterar arquivos .env (credenciais) não é permitido")
        if self.protects_self:
            if parts[0] in PROTECTED_SOURCE_DIRS or (len(parts) == 1 and path.suffix.lower() == ".py"):
                raise PermissionError(
                    "O código do próprio Duque só pode ser alterado pela Forja (auto-desenvolvimento isolado)"
                )
        return path

    def read(self, relative_path: str | Path) -> FileResult:
        path = self.resolve(relative_path)
        if not path.is_file():
            raise FileNotFoundError(str(path))
        return FileResult(str(path), path.read_text(encoding="utf-8"))

    def write(self, relative_path: str | Path, content: str) -> FileResult:
        path = self._resolve_writable(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        existed = path.exists()
        new = encode_text(content)
        # Compara bytes: um arquivo existente em outra codificação não quebra a escrita.
        old = path.read_bytes() if existed and path.is_file() else None
        path.write_bytes(new)
        return FileResult(str(path), created=not existed, changed=old != new)

    def delete(self, relative_path: str | Path) -> FileResult:
        path = self._resolve_writable(relative_path)
        if not path.is_file():
            raise FileNotFoundError(str(path))
        path.unlink()
        return FileResult(str(path), changed=True)

    def list_files(self) -> list[str]:
        files: list[str] = []
        for current, dirs, names in os.walk(self.root):
            dirs[:] = sorted(name for name in dirs if name not in SKIPPED_DIRS)
            base = Path(current)
            for name in sorted(item for item in names if item != ".git"):
                files.append(str((base / name).relative_to(self.root)))
                if len(files) >= MAX_LISTED_FILES:
                    return sorted(files)
        return sorted(files)
