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
        # Depois do clique NUNCA levanta exceção: o clique já aconteceu, e uma
        # "falha" aqui fazia o agente clicar de novo (ação em dobro). O resultado
        # diz com honestidade o que foi e o que não foi confirmado.
        after = self.verification.wait_for_change(before)
        unavailable = not before.available or not after.available
        changed = unavailable or before.fingerprint != after.fingerprint
        problems: list[str] = []
        if unavailable:
            problems.append("não consegui capturar a tela para conferir")
        elif not changed:
            problems.append("a tela não mudou depois do clique")
        if changed and not unavailable and (expected_text or expected_not_text):
            description = after.description
            if expected_text and not self._contains_text(description, expected_text):
                problems.append(f"o texto esperado não apareceu: {expected_text}")
            if expected_not_text and self._contains_text(description, expected_not_text):
                problems.append(f"o texto que deveria sumir continua na tela: {expected_not_text}")
        verified = bool(expected_text or expected_not_text) and not problems
        if verified:
            status, reason = VerificationStatus.VERIFIED, "Resultado esperado confirmado"
        elif unavailable:
            status, reason = VerificationStatus.FAILED, "Cliquei, mas " + "; ".join(problems) + "."
        elif not changed:
            status, reason = VerificationStatus.NOT_CHANGED, "Cliquei, mas " + "; ".join(problems) + ". Olhe a tela antes de tentar de novo."
        else:
            status = VerificationStatus.CHANGED_UNCONFIRMED
            reason = ("A tela mudou, mas " + "; ".join(problems) + ".") if problems else "A tela mudou após o clique; o efeito ainda não foi confirmado."
        return {
            "clicked": True,
            "target": target,
            "message": f"Cliquei em '{text}'. {reason}",
            "verification": {"status": status.value, "changed": changed, "verified": verified, "reason": reason},
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
