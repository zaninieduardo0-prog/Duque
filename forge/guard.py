from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch


@dataclass(slots=True, frozen=True)
class GuardVerdict:
    auto_merge_allowed: bool
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class FileChange:
    status: str  # A, M, D, R...
    path: str


def check_changes(changes: list[FileChange], protected: tuple[str, ...]) -> GuardVerdict:
    """Decide se um conjunto de alterações pode ser aplicado sem aprovação humana."""
    reasons: list[str] = []
    for change in changes:
        path = change.path.replace("\\", "/")
        for pattern in protected:
            if fnmatch(path, pattern):
                reasons.append(f"altera arquivo protegido: {path}")
                break
        if change.status.startswith("D") and (path.startswith("tests/") or path.endswith("_test.py")):
            reasons.append(f"remove teste: {path}")
    return GuardVerdict(not reasons, reasons)
