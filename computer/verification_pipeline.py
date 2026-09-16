from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .verification import Observation, Verification, VerificationResult, VerificationStatus


@dataclass(slots=True, frozen=True)
class VerifiedActionResult:
    action_result: Any
    verification: VerificationResult

    @property
    def verified(self) -> bool:
        return self.verification.status == VerificationStatus.VERIFIED


class VerifiedAction:
    """Executa uma ação entre snapshots e valida o resultado observado."""

    def __init__(self, verification: Verification) -> None:
        self.verification = verification

    def run(
        self,
        action: Callable[[], Any],
        *,
        before: Observation | None = None,
        expected: Callable[[Observation, Observation], bool] | None = None,
    ) -> VerifiedActionResult:
        initial = before or self.verification.snapshot()
        result = action()
        verification = self.verification.verify_change(initial, expected=expected)
        return VerifiedActionResult(result, verification)
