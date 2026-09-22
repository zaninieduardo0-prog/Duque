from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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

    def list_files(self) -> list[str]:
        return sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*") if path.is_file())
