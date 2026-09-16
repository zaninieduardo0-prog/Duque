from __future__ import annotations

from typing import Any

from .perception import ScreenCapture


class WindowsScreenAnalyzer:
    """Análise sem dependência externa: janela ativa e geometria da tela."""

    def analyze(self, capture: ScreenCapture) -> dict[str, Any]:
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return {"status": "ok", "foreground_window": None}

            title_buffer = ctypes.create_unicode_buffer(512)
            class_buffer = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
            user32.GetClassNameW(hwnd, class_buffer, len(class_buffer))

            rect = wintypes.RECT()
            has_rect = bool(user32.GetWindowRect(hwnd, ctypes.byref(rect)))
            geometry = None
            if has_rect:
                geometry = {
                    "left": rect.left,
                    "top": rect.top,
                    "right": rect.right,
                    "bottom": rect.bottom,
                    "width": max(0, rect.right - rect.left),
                    "height": max(0, rect.bottom - rect.top),
                }

            return {
                "status": "ok",
                "foreground_window": {
                    "handle": int(hwnd),
                    "title": title_buffer.value,
                    "class_name": class_buffer.value,
                    "geometry": geometry,
                },
                "screen": {"width": capture.width, "height": capture.height},
                "ocr": {"status": "not_configured"},
            }
        except Exception as exc:
            return {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
