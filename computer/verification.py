from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from typing import Any, Callable

from .perception import ScreenCapture


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
    """Observa o computador e permite validar resultado por mudança ou condição semântica."""

    def __init__(self, perception: Any) -> None:
        self.perception = perception

    def snapshot(self) -> Observation:
        capture = self.perception.screenshot()
        description = self.perception.describe(capture)
        return observe(capture, description)

    def verify_change(self, before: Observation) -> VerificationResult:
        return compare(before, self.snapshot())

    def verify(
        self,
        before: Observation,
        *,
        expected: Callable[[Observation], bool] | None = None,
        confidence: float = 1.0,
    ) -> VerificationResult:
        after = self.snapshot()
        changed = before.fingerprint != after.fingerprint
        if expected is None:
            return compare(before, after)
        try:
            matched = bool(expected(after))
        except Exception as exc:
            return VerificationResult(
                VerificationStatus.FAILED,
                changed,
                before,
                after,
                f"Falha ao avaliar resultado esperado: {type(exc).__name__}: {exc}",
                0.0,
            )
        if matched:
            return VerificationResult(
                VerificationStatus.VERIFIED,
                changed,
                before,
                after,
                "Resultado esperado confirmado",
                max(0.0, min(1.0, float(confidence))),
            )
        status = VerificationStatus.CHANGED_UNCONFIRMED if changed else VerificationStatus.NOT_CHANGED
        return VerificationResult(
            status,
            changed,
            before,
            after,
            "Resultado esperado não confirmado",
            0.0,
        )
