from __future__ import annotations

from typing import Any

from .perception import Perception
from .ui import UIController


class UITools:
    """Ferramentas estruturadas para ações gráficas e percepção da tela."""

    def __init__(
        self,
        controller: UIController | None = None,
        perception: Perception | None = None,
    ) -> None:
        self.controller = controller or UIController()
        self.perception = perception

    def click(self, x: int, y: int, button: str = "left") -> dict[str, Any]:
        self.controller.click(int(x), int(y), button=button)
        return {"clicked": True, "x": int(x), "y": int(y), "button": button}

    def type_text(self, text: str, interval: float = 0.0) -> dict[str, Any]:
        self.controller.type_text(text, interval=float(interval))
        return {"typed": True, "length": len(text)}

    def press(self, key: str) -> dict[str, Any]:
        self.controller.press(key)
        return {"pressed": key}

    def hotkey(self, keys: list[str]) -> dict[str, Any]:
        if not keys:
            raise ValueError("hotkey exige pelo menos uma tecla")
        self.controller.hotkey(*keys)
        return {"pressed": keys}

    def screenshot(self) -> dict[str, Any]:
        if self.perception is None:
            raise RuntimeError("Percepção visual não configurada")
        capture = self.perception.screenshot()
        return self.perception.describe(capture) | {"image": capture.image}

    def register(self, executor: Any) -> None:
        executor.register("ui_click", self.click)
        executor.register("ui_type_text", self.type_text)
        executor.register("ui_press", self.press)
        executor.register("ui_hotkey", self.hotkey)
        executor.register("screenshot", self.screenshot)
