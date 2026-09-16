from __future__ import annotations

from dataclasses import dataclass

from computer.perception import Perception, ScreenCapture
from computer.verification import Verification, compare, observe


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


def test_verification_snapshot_roundtrip() -> None:
    backend = FakeBackend()
    verification = Verification(Perception(backend))
    before = verification.snapshot()
    backend.payload = b"changed"
    result = verification.verify_change(before)
    assert result.changed is True
