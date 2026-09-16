from __future__ import annotations

from dataclasses import dataclass

from computer.perception import Perception, ScreenCapture
from computer.verification import Verification, VerificationStatus


@dataclass
class FakeImage:
    payload: bytes

    def tobytes(self) -> bytes:
        return self.payload


class FakeBackend:
    def __init__(self) -> None:
        self.payload = b"same"

    def capture(self) -> ScreenCapture:
        return ScreenCapture(FakeImage(self.payload), 800, 600)


class FakeAnalyzer:
    def __init__(self) -> None:
        self.title = "Notepad"

    def analyze(self, capture: ScreenCapture) -> dict[str, object]:
        return {
            "status": "ok",
            "foreground_window": {
                "title": self.title,
                "class_name": "Notepad",
            },
        }


def test_snapshot_contains_semantic_description() -> None:
    backend = FakeBackend()
    analyzer = FakeAnalyzer()
    verification = Verification(Perception(backend, analyzer=analyzer))

    observation = verification.snapshot()

    assert observation.description is not None
    assert observation.description["visual_analysis"]["foreground_window"]["title"] == "Notepad"


def test_semantic_expectation_can_verify_without_screen_hash_change() -> None:
    backend = FakeBackend()
    analyzer = FakeAnalyzer()
    verification = Verification(Perception(backend, analyzer=analyzer))
    before = verification.snapshot()

    analyzer.title = "Calculadora"
    result = verification.verify(
        before,
        expected=lambda after: after.description["visual_analysis"]["foreground_window"]["title"] == "Calculadora",
    )

    assert result.status == VerificationStatus.VERIFIED
    assert result.verified is True
    assert result.changed is False


def test_failed_analyzer_does_not_invent_semantics() -> None:
    class BrokenAnalyzer:
        def analyze(self, capture: ScreenCapture) -> dict[str, object]:
            raise RuntimeError("vision indisponível")

    verification = Verification(Perception(FakeBackend(), analyzer=BrokenAnalyzer()))
    observation = verification.snapshot()

    analysis = observation.description["visual_analysis"]
    assert analysis["status"] == "failed"
    assert "vision indisponível" in str(analysis["error"])
