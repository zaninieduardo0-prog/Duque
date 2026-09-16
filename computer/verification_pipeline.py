from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .verification import Observation, Verification, VerificationResult


@dataclass(slots=True, frozen=True)
class VerifiedActionResult:
    action_result: Any
    verification: VerificationResult


class VerifiedAction:
    """Executa uma ação entre snapshots para tornar a execução observável."""

    def __init__(self, verification: Verification) -> None:
        self.verification = verification

    def run(self, action: Callable[[], Any], *, before: Observation | None = None) -> VerifiedActionResult:
        initial = before or self.verification.snapshot()
        result = action()
        verification = self.verification.verify_change(initial)
        return VerifiedActionResult(result, verification)
