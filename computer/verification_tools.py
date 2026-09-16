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
        analysis = description.get("visual_analysis", {})
        ocr = analysis.get("ocr", {}) if isinstance(analysis, dict) else {}
        detected = str(ocr.get("text", ""))
        normalized_text = " ".join(text.casefold().split())
        normalized_detected = " ".join(detected.casefold().split())
        found = bool(normalized_text) and normalized_text in normalized_detected
        status = str(ocr.get("status", "unknown"))

        result = {
            "found": found,
            "requested_text": text,
            "detected_text": detected,
            "ocr_status": status,
        }
        if status != "ok":
            raise RuntimeError(f"Não foi possível verificar o texto na tela: OCR está {status}")
        if not found:
            raise RuntimeError(f"Texto não encontrado na tela: {text}")
        return result

    def register(self, executor: Any) -> None:
        executor.register("screen_snapshot", self.snapshot)
        executor.register("screen_contains_text", self.screen_contains_text)
