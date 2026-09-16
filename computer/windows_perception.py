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
        return ScreenCapture(image=image, width=width, height=height)
