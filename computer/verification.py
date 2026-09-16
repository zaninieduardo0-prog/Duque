from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from .perception import ScreenCapture


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


def observe(capture: ScreenCapture) -> Observation:
    image = capture.image
    try:
        payload = image.tobytes()
    except AttributeError:
        payload = repr(image).encode("utf-8", errors="replace")
    fingerprint = sha256(payload).hexdigest()
    return Observation(capture.width, capture.height, fingerprint, capture.source)


def compare(before: Observation, after: Observation) -> VerificationResult:
    changed = before.fingerprint != after.fingerprint
    reason = "A tela mudou" if changed else "Nenhuma mudança visual detectada"
    return VerificationResult(changed, before, after, reason)


class Verification:
    """Compara observações antes/depois sem assumir o significado da tela."""

    def __init__(self, perception: Any) -> None:
        self.perception = perception

    def snapshot(self) -> Observation:
        return observe(self.perception.screenshot())

    def verify_change(self, before: Observation) -> VerificationResult:
        after = self.snapshot()
        return compare(before, after)
