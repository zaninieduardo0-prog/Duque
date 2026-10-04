from __future__ import annotations


class UIController:
    """Abstração de automação gráfica. Backend real será plugável no runtime."""

    def click(self, x: int, y: int, *, button: str = "left") -> None:
        self._require_backend()

    def type_text(self, text: str, *, interval: float = 0.0) -> None:
        self._require_backend()

    def press(self, key: str) -> None:
        self._require_backend()

    def hotkey(self, *keys: str) -> None:
        self._require_backend()

    def _require_backend(self) -> None:
        raise RuntimeError("Backend de automação de interface ainda não configurado")
