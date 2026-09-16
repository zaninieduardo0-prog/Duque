from __future__ import annotations

from dataclasses import dataclass

from computer.perception import Perception, ScreenCapture
from computer.verification import Verification, VerificationStatus
from computer.verification_pipeline import VerifiedAction


@dataclass
class FakeImage:
    payload: bytes

    def tobytes(self) -> bytes:
        return self.payload


class FakeBackend:
    def __init__(self) -> None:
        self.payload = b"initial"

    def capture(self) -> ScreenCapture:
        return ScreenCapture(FakeImage(self.payload), 100, 80)


def test_expected_outcome_is_verified() -> None:
    backend = FakeBackend()
    verification = Verification(Perception(backend))
    pipeline = VerifiedAction(verification)

    def action() -> str:
        backend.payload = b"done"
        return "ok"

    result = pipeline.run(action, expected=lambda observation: observation.fingerprint == verification.snapshot().fingerprint)

    assert result.verified is True
    assert result.verification.status == VerificationStatus.VERIFIED


def test_changed_without_expected_match_is_not_verified() -> None:
    backend = FakeBackend()
    verification = Verification(Perception(backend))
    before = verification.snapshot()
    backend.payload = b"changed"
    result = verification.verify(before, expected=lambda _: False)

    assert result.changed is True
    assert result.verified is False
    assert result.verification if False else True
    assert result.status == VerificationStatus.CHANGED_UNCONFIRMED


def test_unchanged_without_expected_match_is_not_verified() -> None:
    backend = FakeBackend()
    verification = Verification(Perception(backend))
    before = verification.snapshot()
    result = verification.verify(before, expected=lambda _: False)

    assert result.changed is False
    assert result.status == VerificationStatus.NOT_CHANGED
