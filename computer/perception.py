from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(slots=True, frozen=True)
class ScreenCapture:
    """Resultado portável de uma captura de tela."""

    image: Any
    width: int
    height: int
    source: str = "screen"


class ScreenBackend(Protocol):
    def capture(self) -> ScreenCapture: ...


class Perception:
    """Camada de percepção visual; OCR/visão por modelo entram acima dela."""

    def __init__(self, backend: ScreenBackend) -> None:
        self.backend = backend

    def screenshot(self) -> ScreenCapture:
        return self.backend.capture()

    def describe(self, capture: ScreenCapture) -> dict[str, Any]:
        return {
            "source": capture.source,
            "width": capture.width,
            "height": capture.height,
            "visual_analysis": "not_available",
        }
