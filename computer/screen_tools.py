from __future__ import annotations

from typing import Any

from .verification import Verification


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

        needle = " ".join(text.casefold().split())
        matches: list[dict[str, Any]] = []
        for element in vision.get("elements", []):
            label = " ".join(str(element.get("text", "")).casefold().split())
            confidence = float(element.get("confidence", 0.0))
            if needle in label and confidence >= confidence_floor:
                matches.append(element)

        if not matches:
            raise RuntimeError(f"Elemento não encontrado com confiança suficiente: {text}")
        matches.sort(key=lambda item: float(item.get("confidence", 0.0)), reverse=True)
        if len(matches) > 1 and abs(float(matches[0].get("confidence", 0.0)) - float(matches[1].get("confidence", 0.0))) < 0.05:
            raise RuntimeError(f"Busca ambígua para '{text}': múltiplos elementos têm confiança semelhante")

        best = matches[0]
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
    def _vision_payload(description: dict[str, Any]) -> dict[str, Any]:
        # Perception direta usa visual_analysis; o compositor usa o nome do analyzer.
        direct = description.get("visual_analysis")
        if isinstance(direct, dict) and "elements" in direct:
            return direct
        nested = description.get("ModelVisionAnalyzer")
        if isinstance(nested, dict):
            return nested
        return {"status": "unavailable", "reason": "model_vision_not_found"}

    def register(self, executor: Any) -> None:
        executor.register("screen_find", self.find)
