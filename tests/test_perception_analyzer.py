from __future__ import annotations

from dataclasses import dataclass

from computer.perception import Perception, ScreenCapture


@dataclass
class FakeImage:
    payload: bytes


class FakeBackend:
    def capture(self) -> ScreenCapture:
        return ScreenCapture(FakeImage(b"screen"), 320, 200)


class FakeAnalyzer:
    def analyze(self, capture: ScreenCapture) -> dict[str, object]:
        return {"status": "ok", "text": "Duque"}


def test_perception_uses_pluggable_analyzer() -> None:
    result = Perception(FakeBackend(), analyzer=FakeAnalyzer()).describe(FakeBackend().capture())
    assert result["width"] == 320
    assert result["visual_analysis"] == {"status": "ok", "text": "Duque"}


def test_perception_does_not_fake_visual_analysis_when_unavailable() -> None:
    result = Perception(FakeBackend()).describe(FakeBackend().capture())
    assert result["visual_analysis"] == {"status": "not_available"}
