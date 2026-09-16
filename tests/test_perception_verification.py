from __future__ import annotations

from dataclasses import dataclass

from computer.perception import Perception, ScreenCapture
from computer.verification import Verification, VerificationStatus, compare, observe
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


def test_observation_detects_change() -> None:
    backend = FakeBackend()
    perception = Perception(backend)
    before = observe(perception.screenshot())
    backend.payload = b"changed"
    after = observe(perception.screenshot())
    result = compare(before, after)
    assert result.changed is True
    assert result.before.fingerprint != result.after.fingerprint
    assert result.status == VerificationStatus.CHANGED_UNCONFIRMED


def test_verification_snapshot_roundtrip() -> None:
    backend = FakeBackend()
    verification = Verification(Perception(backend))
    before = verification.snapshot()
    backend.payload = b"changed"
    result = verification.verify_change(before)
    assert result.changed is True
    assert result.status == VerificationStatus.CHANGED_UNCONFIRMED


def test_verification_can_confirm_expected_outcome() -> None:
    backend = FakeBackend()
    verification = Verification(Perception(backend))
    before = verification.snapshot()
    backend.payload = b"expected"
    result = verification.verify(
        before,
        expected=lambda after: after.fingerprint == observe(backend.capture()).fingerprint,
    )
    assert result.status == VerificationStatus.VERIFIED
    assert result.verified is True
    assert result.confidence == 1.0


def test_verification_rejects_unconfirmed_expected_outcome() -> None:
    backend = FakeBackend()
    verification = Verification(Perception(backend))
    before = verification.snapshot()
    result = verification.verify(before, expected=lambda _after: False)
    assert result.status == VerificationStatus.NOT_CHANGED
    assert result.verified is False


def test_verified_action_reports_verification() -> None:
    backend = FakeBackend()
    verification = Verification(Perception(backend))

    def action() -> str:
        backend.payload = b"done"
        return "ok"

    result = VerifiedAction(verification).run(
        action,
        expected=lambda _after: True,
    )
    assert result.action_result == "ok"
    assert result.verified is True
