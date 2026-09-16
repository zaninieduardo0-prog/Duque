from __future__ import annotations

from dataclasses import dataclass

from computer.perception import Perception, ScreenCapture
from computer.verification import Verification
from computer.verified_ui import VerifiedScreenActions


@dataclass
class FakeImage:
    payload: bytes

    def tobytes(self) -> bytes:
        return self.payload


class FakeBackend:
    def __init__(self) -> None:
        self.payload = b"before"

    def capture(self) -> ScreenCapture:
        return ScreenCapture(FakeImage(self.payload), 100, 80)


class FakeVision:
    def analyze(self, capture: ScreenCapture):
        return {
            "status": "ok",
            "elements": [
                {
                    "type": "button",
                    "text": "Continuar",
                    "x": 10,
                    "y": 20,
                    "width": 40,
                    "height": 20,
                    "confidence": 0.95,
                }
            ],
        }


class FakeController:
    def __init__(self, backend: FakeBackend) -> None:
        self.backend = backend
        self.calls: list[tuple[int, int]] = []

    def click(self, x: int, y: int, *, button: str = "left") -> None:
        self.calls.append((x, y))
        self.backend.payload = b"after"


def test_click_text_uses_visual_center_and_verifies_change() -> None:
    backend = FakeBackend()
    perception = Perception(backend, analyzer=FakeVision())
    verification = Verification(perception)
    controller = FakeController(backend)

    result = VerifiedScreenActions(controller, verification).click_text("Continuar")

    assert controller.calls == [(30, 30)]
    assert result["clicked"] is True
    assert result["verification"]["changed"] is True


def test_click_text_fails_when_screen_does_not_change() -> None:
    backend = FakeBackend()
    perception = Perception(backend, analyzer=FakeVision())
    verification = Verification(perception)

    class NoChangeController(FakeController):
        def click(self, x: int, y: int, *, button: str = "left") -> None:
            self.calls.append((x, y))

    controller = NoChangeController(backend)
    try:
        VerifiedScreenActions(controller, verification).click_text("Continuar")
    except RuntimeError as exc:
        assert "não produziu mudança" in str(exc)
    else:
        raise AssertionError("O clique sem mudança deveria falhar")
