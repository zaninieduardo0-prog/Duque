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


class ScreenAnalyzer(Protocol):
    """Contrato para OCR, visão por modelo ou analisadores locais."""

    def analyze(self, capture: ScreenCapture) -> dict[str, Any]: ...


class NullScreenAnalyzer:
    """Analisador seguro que não inventa conteúdo visual."""

    def analyze(self, capture: ScreenCapture) -> dict[str, Any]:
        return {"status": "not_available"}


class Perception:
    """Camada de percepção visual; o analisador pode ser trocado sem alterar o backend."""

    def __init__(self, backend: ScreenBackend, analyzer: ScreenAnalyzer | None = None) -> None:
        self.backend = backend
        self.analyzer = analyzer or NullScreenAnalyzer()

    def screenshot(self) -> ScreenCapture:
        return self.backend.capture()

    def analyze(self, capture: ScreenCapture) -> dict[str, Any]:
        try:
            return self.analyzer.analyze(capture)
        except Exception as exc:
            return {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }

    def describe(self, capture: ScreenCapture) -> dict[str, Any]:
        analysis = self.analyze(capture)
        return {
            "source": capture.source,
            "width": capture.width,
            "height": capture.height,
            "visual_analysis": analysis,
        }
