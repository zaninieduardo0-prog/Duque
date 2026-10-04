from __future__ import annotations

from typing import Any

from .verification import Verification


class VerificationTools:
    """Ferramentas para observar e consultar semanticamente a interface."""

    def __init__(self, verification: Verification) -> None:
        self.verification = verification

    def snapshot(self) -> dict[str, Any]:
        observation = self.verification.snapshot()
        return {
            "width": observation.width,
            "height": observation.height,
            "fingerprint": observation.fingerprint,
            "source": observation.source,
            "description": observation.description,
        }

    def screen_contains_text(self, text: str) -> dict[str, Any]:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text não pode ser vazio")

        observation = self.verification.snapshot()
        description = observation.description or {}
        detected, source, statuses = self._detected_text(description.get("visual_analysis"))
        if source is None:
            detail = ", ".join(f"{name} {status}" for name, status in statuses) or "nenhuma análise visual"
            raise RuntimeError(f"Não foi possível verificar o texto na tela: sem OCR nem visão disponível ({detail})")

        normalized_text = " ".join(text.casefold().split())
        normalized_detected = " ".join(detected.casefold().split())
        return {
            "found": normalized_text in normalized_detected,
            "requested_text": text,
            "detected_text": detected,
            "source": source,
            "ocr_status": "ok",
        }

    @staticmethod
    def _detected_text(analysis: Any) -> tuple[str, str | None, list[tuple[str, str]]]:
        """Junta o texto lido pelas fontes disponíveis (OCR local e/ou visão por modelo).

        Aceita a análise direta do WindowsScreenAnalyzer (``ocr`` na raiz) e a do
        compositor (``WindowsScreenAnalyzer``/``ModelVisionAnalyzer`` aninhados).
        """
        if not isinstance(analysis, dict):
            return "", None, []
        texts: list[str] = []
        sources: list[str] = []
        statuses: list[tuple[str, str]] = []

        local = analysis.get("WindowsScreenAnalyzer")
        local = local if isinstance(local, dict) else analysis
        ocr = local.get("ocr")
        if isinstance(ocr, dict):
            status = str(ocr.get("status", "unknown"))
            statuses.append(("OCR", status))
            if status == "ok":
                texts.append(str(ocr.get("text", "")))
                sources.append("ocr")

        vision = analysis.get("ModelVisionAnalyzer")
        vision = vision if isinstance(vision, dict) else (analysis if "ocr_text" in analysis else None)
        if isinstance(vision, dict):
            status = str(vision.get("status", "unknown"))
            statuses.append(("visão", status))
            if status == "ok":
                texts.append(str(vision.get("ocr_text", "")))
                elements = vision.get("elements")
                if isinstance(elements, list):
                    texts.extend(str(item.get("text", "")) for item in elements if isinstance(item, dict))
                sources.append("model_vision")

        if not sources:
            return "", None, statuses
        return "\n".join(item for item in texts if item), "+".join(sources), statuses

    def register(self, executor: Any) -> None:
        executor.register("screen_snapshot", self.snapshot)
        executor.register("screen_contains_text", self.screen_contains_text)
