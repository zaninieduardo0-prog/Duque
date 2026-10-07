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
        detected, status = screen_text(observation.description or {})
        normalized_text = " ".join(text.casefold().split())
        normalized_detected = " ".join(detected.casefold().split())
        if status != "ok":
            # Não dá para ler a tela: isso sim é falha (não é "o texto não está lá").
            return {
                "success": False, "found": None, "requested_text": text, "ocr_status": status,
                "error": f"Não consigo ler o texto da tela (OCR {status}). DUQUE_ENABLE_OCR=1 com o Tesseract instalado liga a leitura.",
            }
        found = bool(normalized_text) and normalized_text in normalized_detected
        # Texto ausente é uma RESPOSTA ("não está"), não um erro: antes levantava
        # exceção e o agente repetia a ação anterior achando que tinha falhado.
        return {
            "found": found,
            "requested_text": text,
            "detected_text": detected[:2000],
            "ocr_status": status,
            "message": f"O texto '{text}' {'está' if found else 'não está'} na tela.",
        }

    def register(self, executor: Any) -> None:
        executor.register("screen_snapshot", self.snapshot)
        executor.register("screen_contains_text", self.screen_contains_text)


def screen_text(description: dict[str, Any]) -> tuple[str, str]:
    """Texto lido da tela (OCR local ou visão por modelo) e o status da leitura."""
    analysis = description.get("visual_analysis", {}) if isinstance(description, dict) else {}
    if not isinstance(analysis, dict):
        return "", "unknown"
    sources = [analysis] + [value for value in analysis.values() if isinstance(value, dict)]
    statuses: list[str] = []
    for source in sources:
        ocr = source.get("ocr")
        if isinstance(ocr, dict):
            statuses.append(str(ocr.get("status", "unknown")))
            if ocr.get("status") == "ok":
                return str(ocr.get("text", "")), "ok"
        if source.get("status") == "ok" and isinstance(source.get("ocr_text"), str) and source.get("ocr_text"):
            return str(source["ocr_text"]), "ok"
    return "", statuses[0] if statuses else str(analysis.get("status", "unknown"))
