from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from typing import Any

from .perception import ScreenCapture

# A interface costuma levar algumas centenas de ms para reagir (animações,
# janelas abrindo). Antes de concluir "nada mudou", observa por ~1,5s.
CHANGE_POLL_ATTEMPTS = 10
CHANGE_POLL_INTERVAL = 0.15


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    CHANGED_UNCONFIRMED = "changed_unconfirmed"
    NOT_CHANGED = "not_changed"
    FAILED = "failed"


@dataclass(slots=True, frozen=True)
class Observation:
    width: int
    height: int
    fingerprint: str
    source: str = "screen"
    description: dict[str, Any] | None = None


@dataclass(slots=True, frozen=True)
class VerificationResult:
    status: VerificationStatus
    changed: bool
    before: Observation
    after: Observation
    reason: str
    confidence: float = 0.0

    @property
    def verified(self) -> bool:
        return self.status == VerificationStatus.VERIFIED


def observe(capture: ScreenCapture, description: dict[str, Any] | None = None) -> Observation:
    image = capture.image
    try:
        payload = image.tobytes()
    except AttributeError:
        payload = repr(image).encode("utf-8", errors="replace")
    fingerprint = sha256(payload).hexdigest()
    return Observation(capture.width, capture.height, fingerprint, capture.source, description)


def compare(before: Observation, after: Observation) -> VerificationResult:
    changed = before.fingerprint != after.fingerprint
    status = VerificationStatus.CHANGED_UNCONFIRMED if changed else VerificationStatus.NOT_CHANGED
    reason = "A tela mudou, mas o resultado esperado não foi confirmado" if changed else "Nenhuma mudança visual detectada"
    return VerificationResult(status, changed, before, after, reason, 0.0)


class Verification:
    """Observa o computador e permite validar resultado por mudança visual."""

    def __init__(
        self,
        perception: Any,
        *,
        poll_attempts: int = CHANGE_POLL_ATTEMPTS,
        poll_interval: float = CHANGE_POLL_INTERVAL,
    ) -> None:
        self.perception = perception
        self.poll_attempts = max(1, int(poll_attempts))
        self.poll_interval = max(0.0, float(poll_interval))

    def snapshot(self) -> Observation:
        """Captura completa: impressão digital + descrição (OCR/visão). Cara."""
        capture = self.perception.screenshot()
        description = self.perception.describe(capture)
        return observe(capture, description)

    def fingerprint(self) -> Observation:
        """Captura barata: só a impressão digital, sem OCR nem visão por modelo."""
        return observe(self.perception.screenshot())

    def verify_change(self, before: Observation) -> VerificationResult:
        """Aguarda a tela mudar em relação a ``before``.

        ``before`` pode vir de ``snapshot()`` ou de ``fingerprint()``: os dois
        usam a mesma impressão digital. As capturas posteriores são baratas.
        """
        after = self.fingerprint()
        for _ in range(self.poll_attempts - 1):
            if after.fingerprint != before.fingerprint:
                break
            time.sleep(self.poll_interval)
            after = self.fingerprint()
        return compare(before, after)
