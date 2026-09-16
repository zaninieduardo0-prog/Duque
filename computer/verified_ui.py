from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .screen_tools import ScreenTools
from .ui import UIController
from .verification import Verification, VerificationStatus


@dataclass(slots=True, frozen=True)
class ScreenActionResult:
    action: dict[str, Any]
    verification: dict[str, Any]


class VerifiedScreenActions:
    """Ações gráficas guiadas por visão e verificadas pelo estado posterior."""

    def __init__(self, controller: UIController, verification: Verification) -> None:
        self.controller = controller
        self.verification = verification
        self.screen = ScreenTools(verification)

    def click_text(self, text: str, min_confidence: float = 0.65) -> dict[str, Any]:
        target = self.screen.find(text, min_confidence=min_confidence)
        point = target["click_point"]
        before = self.verification.snapshot()
        self.controller.click(point["x"], point["y"])
        after = self.verification.snapshot()

        changed = before.fingerprint != after.fingerprint
        if not changed:
            raise RuntimeError(f"Clique em '{text}' não produziu mudança visual detectável")

        return {
            "clicked": True,
            "target": target,
            "verification": {
                "status": VerificationStatus.CHANGED_UNCONFIRMED.value,
                "changed": True,
                "reason": "A tela mudou após o clique; o efeito semântico ainda não foi confirmado.",
            },
        }

    def register(self, executor: Any) -> None:
        executor.register("screen_click_text", self.click_text)
