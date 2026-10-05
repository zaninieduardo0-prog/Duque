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
    """Acesso ao workspace e a pastas pessoais explicitamente permitidas."""
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        home = Path.home().resolve()
        self.allowed_roots = {
            self.root,
            home / "Desktop",
            home / "Documents",
            home / "Downloads",
            home / "Pictures",
            home / "Videos",
            home / "Music",
        }

    @staticmethod
    def _inside(candidate: Path, root: Path) -> bool:
        try:
            candidate.relative_to(root)
            return True
        except ValueError:
            return False

    def resolve(self, relative_path: str | Path) -> Path:
        raw = Path(relative_path).expanduser()
        candidate = raw.resolve() if raw.is_absolute() else (self.root / raw).resolve()
        if any(self._inside(candidate, allowed) for allowed in self.allowed_roots):
            return candidate
        raise PermissionError("Caminho fora do workspace e das pastas pessoais permitidas")

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

    def list_files(self, path: str | Path = ".") -> list[str]:
        base = self.resolve(path)
        if base.is_file():
            return [str(base)]
        return sorted(str(item) for item in base.rglob("*") if item.is_file())
