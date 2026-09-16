from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .verification import Observation, Verification, VerificationResult


@dataclass(slots=True, frozen=True)
class VerifiedActionResult:
    action_result: Any
    verification: VerificationResult

    @property
    def verified(self) -> bool:
        return self.verification.verified


class VerifiedAction:
    """Executa uma ação, observa o estado e valida o resultado esperado."""

    def __init__(self, verification: Verification) -> None:
        self.verification = verification

    def run(
        self,
        action: Callable[[], Any],
        *,
        before: Observation | None = None,
        expected: Callable[[Observation], bool] | None = None,
        confidence: float = 1.0,
    ) -> VerifiedActionResult:
        initial = before or self.verification.snapshot()
        result = action()
        verification = self.verification.verify(
            initial,
            expected=expected,
            confidence=confidence,
        )
        return VerifiedActionResult(result, verification)
