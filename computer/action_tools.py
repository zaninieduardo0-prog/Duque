from __future__ import annotations

from typing import Any

from .screen_tools import ScreenTools
from .ui import UIController


class ComputerActionTools:
    """Ações compostas que ligam percepção visual a controle de interface."""

    def __init__(self, screen_tools: ScreenTools, controller: UIController) -> None:
        self.screen_tools = screen_tools
        self.controller = controller

    def click_text(self, text: str, min_confidence: float = 0.65) -> dict[str, Any]:
        """Localiza texto na tela e clica no centro do elemento identificado."""
        found = self.screen_tools.find(text, min_confidence=min_confidence)
        point = found["click_point"]
        self.controller.click(point["x"], point["y"])
        return {
            "clicked": True,
            "text": text,
            "click_point": point,
            "element": found["element"],
        }

    def register(self, executor: Any) -> None:
        executor.register("screen_click_text", self.click_text)
