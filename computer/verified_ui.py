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

    def click_text(
        self,
        text: str,
        min_confidence: float = 0.65,
        expected_text: str | None = None,
        expected_not_text: str | None = None,
    ) -> dict[str, Any]:
        target = self.screen.find(text, min_confidence=min_confidence)
        point = target["click_point"]
        before = self.verification.snapshot()
        self.controller.click(point["x"], point["y"])
        after = self.verification.snapshot()

        changed = before.fingerprint != after.fingerprint
        if not changed:
            raise RuntimeError(f"Clique em '{text}' não produziu mudança visual detectável")

        if expected_text and not self._contains_text(after.description, expected_text):
            raise RuntimeError(f"Clique em '{text}' mudou a tela, mas o texto esperado não apareceu: {expected_text}")

        if expected_not_text and self._contains_text(after.description, expected_not_text):
            raise RuntimeError(f"Clique em '{text}' mudou a tela, mas o texto que deveria desaparecer ainda está presente: {expected_not_text}")

        verified = bool(expected_text or expected_not_text)
        return {
            "clicked": True,
            "target": target,
            "verification": {
                "status": VerificationStatus.VERIFIED.value if verified else VerificationStatus.CHANGED_UNCONFIRMED.value,
                "changed": True,
                "verified": verified,
                "reason": "Resultado esperado confirmado" if verified else "A tela mudou após o clique; o efeito semântico ainda não foi confirmado.",
            },
        }

    @classmethod
    def _contains_text(cls, value: Any, expected: str) -> bool:
        needle = " ".join(expected.casefold().split())
        if not needle:
            return True
        if isinstance(value, str):
            return needle in " ".join(value.casefold().split())
        if isinstance(value, dict):
            return any(cls._contains_text(item, expected) for item in value.values())
        if isinstance(value, (list, tuple, set)):
            return any(cls._contains_text(item, expected) for item in value)
        return False

    def register(self, executor: Any) -> None:
        executor.register("screen_click_text", self.click_text)
