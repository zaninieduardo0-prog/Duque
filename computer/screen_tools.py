from __future__ import annotations

import re
from typing import Any

from .verification import Verification


def _normalize(text: Any) -> str:
    return " ".join(str(text).casefold().split())


class ScreenTools:
    """Consultas semânticas sobre elementos identificados na tela."""

    def __init__(self, verification: Verification) -> None:
        self.verification = verification

    def find(self, text: str, min_confidence: float = 0.65) -> dict[str, Any]:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text não pode ser vazio")
        confidence_floor = max(0.0, min(1.0, float(min_confidence)))
        observation = self.verification.snapshot()
        description = observation.description or {}
        vision = self._vision_payload(description)
        if vision.get("status") != "ok":
            raise RuntimeError(f"Visão multimodal indisponível: {vision.get('reason') or vision.get('error') or vision.get('status')}")

        best = self._best_match(text, vision.get("elements", []), confidence_floor)
        try:
            x, y, width, height = (float(best[key]) for key in ("x", "y", "width", "height"))
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"Elemento visual inválido: {best}") from exc
        if width <= 0 or height <= 0:
            raise RuntimeError("Elemento visual possui dimensões inválidas")

        return {
            "found": True,
            "text": text,
            "element": best,
            "click_point": {"x": int(x + width / 2), "y": int(y + height / 2)},
        }

    @staticmethod
    def _best_match(text: str, elements: Any, confidence_floor: float) -> dict[str, Any]:
        """Prefere rótulos idênticos; senão aceita o texto como palavra(s) inteira(s)."""
        needle = _normalize(text)
        pattern = re.compile(r"(?<!\w)" + re.escape(needle) + r"(?!\w)")
        exact: list[dict[str, Any]] = []
        partial: list[dict[str, Any]] = []
        for element in elements if isinstance(elements, list) else []:
            if not isinstance(element, dict):
                continue
            try:
                confidence = float(element.get("confidence", 0.0))
            except (TypeError, ValueError):
                continue
            if confidence < confidence_floor:
                continue
            label = _normalize(element.get("text", ""))
            if label == needle:
                exact.append(element)
            elif pattern.search(label):
                partial.append(element)

        matches = exact or partial
        if not matches:
            raise RuntimeError(f"Elemento não encontrado com confiança suficiente: {text}")
        matches.sort(key=lambda item: float(item.get("confidence", 0.0)), reverse=True)
        if len(matches) > 1 and abs(float(matches[0].get("confidence", 0.0)) - float(matches[1].get("confidence", 0.0))) < 0.05:
            raise RuntimeError(f"Busca ambígua para '{text}': múltiplos elementos têm confiança semelhante")
        return matches[0]

    @staticmethod
    def _vision_payload(description: dict[str, Any]) -> dict[str, Any]:
        # Perception.describe guarda a análise em visual_analysis. Com visão por
        # modelo ligada, ela vem do compositor, aninhada pelo nome do analyzer.
        analysis = description.get("visual_analysis")
        if isinstance(analysis, dict):
            if "elements" in analysis:
                return analysis
            nested = analysis.get("ModelVisionAnalyzer")
            if isinstance(nested, dict):
                return nested
        legacy = description.get("ModelVisionAnalyzer")
        if isinstance(legacy, dict):
            return legacy
        return {"status": "unavailable", "reason": "visão por modelo desativada (DUQUE_ENABLE_MODEL_VISION)"}

    def register(self, executor: Any) -> None:
        executor.register("screen_find", self.find)
