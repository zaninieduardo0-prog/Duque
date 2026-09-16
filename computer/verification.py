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


@dataclass(slots=True, frozen=True)
class VerificationResult:
    changed: bool
    before: Observation
    after: Observation
    reason: str
    status: VerificationStatus = VerificationStatus.CHANGED_UNCONFIRMED
    expected: bool | None = None
    confidence: float = 0.0


def observe(capture: ScreenCapture) -> Observation:
    image = capture.image
    try:
        payload = image.tobytes()
    except AttributeError:
        payload = repr(image).encode("utf-8", errors="replace")
    fingerprint = sha256(payload).hexdigest()
    return Observation(capture.width, capture.height, fingerprint, capture.source)


def compare(
    before: Observation,
    after: Observation,
    *,
    expected: Callable[[Observation, Observation], bool] | None = None,
) -> VerificationResult:
    changed = before.fingerprint != after.fingerprint
    expected_result: bool | None = None
    if expected is not None:
        try:
            expected_result = bool(expected(before, after))
        except Exception as exc:
            return VerificationResult(
                changed, before, after,
                f"Verificador falhou: {type(exc).__name__}: {exc}",
                VerificationStatus.FAILED, None, 0.0,
            )

    if expected_result is True:
        return VerificationResult(changed, before, after, "Resultado esperado confirmado", VerificationStatus.VERIFIED, True, 1.0)
    if expected_result is False:
        return VerificationResult(changed, before, after, "Resultado esperado não confirmado", VerificationStatus.FAILED, False, 0.0)
    if changed:
        return VerificationResult(True, before, after, "A tela mudou, mas o resultado ainda não foi confirmado", VerificationStatus.CHANGED_UNCONFIRMED, None, 0.5)
    return VerificationResult(False, before, after, "Nenhuma mudança visual detectada", VerificationStatus.NOT_CHANGED, None, 0.0)


class Verification:
    """Compara observações e permite validadores de resultado sem assumir que mudança = sucesso."""

    def __init__(self, perception: Any) -> None:
        self.perception = perception

    def snapshot(self) -> Observation:
        return observe(self.perception.screenshot())

    def verify_change(
        self,
        before: Observation,
        *,
        expected: Callable[[Observation, Observation], bool] | None = None,
    ) -> VerificationResult:
        after = self.snapshot()
        return compare(before, after, expected=expected)
