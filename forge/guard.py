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


def touches_workflows(changes: list[FileChange]) -> bool:
    """Mudanças em .github/ não podem nem ser enviadas: o CI rodaria o workflow alterado."""
    return any(change.path.replace("\\", "/").startswith(".github/") for change in changes)


def _is_test(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return path.startswith("tests/") or "/tests/" in path or name.endswith("_test.py")


def check_changes(changes: list[FileChange], protected: tuple[str, ...]) -> GuardVerdict:
    """Decide se um conjunto de alterações pode ser aplicado sem aprovação humana."""
    reasons: list[str] = []
    for change in changes:
        path = change.path.replace("\\", "/")
        for pattern in protected:
            if fnmatch(path, pattern):
                reasons.append(f"altera arquivo protegido: {path}")
                break
        if _is_test(path):
            # Testes novos são bem-vindos; mexer nos existentes pode enfraquecê-los.
            if change.status.startswith("D"):
                reasons.append(f"remove teste: {path}")
            elif not change.status.startswith("A"):
                reasons.append(f"altera teste existente: {path}")
    return GuardVerdict(not reasons, reasons)
