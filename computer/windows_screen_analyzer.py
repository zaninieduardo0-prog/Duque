from __future__ import annotations

import os
from typing import Any

from .perception import ScreenCapture


class WindowsScreenAnalyzer:
    """Percepção local do Windows: janela ativa e OCR opcional."""

    def analyze(self, capture: ScreenCapture) -> dict[str, Any]:
        try:
            context = self._foreground_window()
            ocr = self._ocr(capture)
            return {
                "status": "ok",
                "foreground_window": context,
                "screen": {"width": capture.width, "height": capture.height},
                "ocr": ocr,
            }
        except Exception as exc:
            return {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}

    @staticmethod
    def _foreground_window() -> dict[str, Any] | None:
        import ctypes
        from ctypes import wintypes

        user32 = getattr(ctypes, "windll").user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None

        title_buffer = ctypes.create_unicode_buffer(512)
        class_buffer = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
        user32.GetClassNameW(hwnd, class_buffer, len(class_buffer))

        rect = wintypes.RECT()
        geometry = None
        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            geometry = {
                "left": rect.left,
                "top": rect.top,
                "right": rect.right,
                "bottom": rect.bottom,
                "width": max(0, rect.right - rect.left),
                "height": max(0, rect.bottom - rect.top),
            }

        return {
            "handle": int(hwnd),
            "title": title_buffer.value,
            "class_name": class_buffer.value,
            "geometry": geometry,
        }

    @staticmethod
    def _ocr(capture: ScreenCapture) -> dict[str, Any]:
        """OCR é opt-in: não envia imagens para terceiros e não adiciona custo por padrão."""
        if os.getenv("DUQUE_ENABLE_OCR", "0").casefold() not in {"1", "true", "yes", "on"}:
            return {"status": "disabled"}

        try:
            import pytesseract
        except ImportError:
            return {"status": "unavailable", "reason": "pytesseract não instalado"}

        try:
            text = pytesseract.image_to_string(capture.image, lang="por+eng")
            return {
                "status": "ok",
                "text": text.strip(),
                "characters": len(text.strip()),
            }
        except Exception as exc:
            return {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
