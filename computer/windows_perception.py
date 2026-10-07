from __future__ import annotations

from typing import Any

from .perception import ScreenCapture


class WindowsScreenBackend:
    """Captura de tela no Windows usando Pillow, quando instalado."""

    def capture(self) -> ScreenCapture:
        try:
            from PIL import ImageGrab
        except ImportError as exc:
            raise RuntimeError(
                "Captura de tela requer Pillow. Instale a dependência antes de ativar a percepção visual."
            ) from exc

        image: Any = ImageGrab.grab(all_screens=True)
        width, height = image.size
        origin_x, origin_y = _virtual_screen_origin()
        return ScreenCapture(image=image, width=width, height=height, origin_x=origin_x, origin_y=origin_y)


def _virtual_screen_origin() -> tuple[int, int]:
    """Canto superior esquerdo da área de trabalho virtual (onde começa o print de todas as telas)."""
    try:
        import ctypes

        user32 = getattr(ctypes, "windll").user32
        return int(user32.GetSystemMetrics(76)), int(user32.GetSystemMetrics(77))  # SM_X/YVIRTUALSCREEN
    except Exception:
        return 0, 0
