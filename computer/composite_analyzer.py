from __future__ import annotations

from typing import Any

from .perception import ScreenCapture, ScreenAnalyzer


class CompositeScreenAnalyzer(ScreenAnalyzer):
    """Combina percepção local e percepção multimodal sem misturar responsabilidades."""

    def __init__(self, *analyzers: ScreenAnalyzer) -> None:
        self.analyzers = tuple(analyzers)

    def analyze(self, capture: ScreenCapture) -> dict[str, Any]:
        result: dict[str, Any] = {"status": "failed", "sources": []}
        for analyzer in self.analyzers:
            try:
                data = analyzer.analyze(capture)
            except Exception as exc:
                data = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
            name = type(analyzer).__name__
            result["sources"].append({"name": name, "data": data})
            result[name] = data
            if isinstance(data, dict) and data.get("status") == "ok":
                result["status"] = "ok"
        return result
