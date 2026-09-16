from __future__ import annotations

from typing import Any

from .verification import Verification


class VerificationTools:
    """Ferramentas para observar e verificar mudanças na interface."""

    def __init__(self, verification: Verification) -> None:
        self.verification = verification

    def snapshot(self) -> dict[str, Any]:
        observation = self.verification.snapshot()
        return {
            "width": observation.width,
            "height": observation.height,
            "fingerprint": observation.fingerprint,
            "source": observation.source,
        }

    def register(self, executor: Any) -> None:
        executor.register("screen_snapshot", self.snapshot)
