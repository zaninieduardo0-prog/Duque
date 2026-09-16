from __future__ import annotations

import ctypes
import platform
import time
from typing import Any

from .ui import UIController


class WindowsUIController(UIController):
    """Backend Windows sem dependências externas para mouse/teclado básicos."""

    def __init__(self) -> None:
        if platform.system() != "Windows":
            raise RuntimeError("WindowsUIController requer Windows")
        self._user32 = ctypes.windll.user32

    def click(self, x: int, y: int, *, button: str = "left") -> None:
        self._user32.SetCursorPos(int(x), int(y))
        if button == "left":
            down, up = 0x0002, 0x0004
        elif button == "right":
            down, up = 0x0008, 0x0010
        else:
            raise ValueError(f"Botão não suportado: {button}")
        self._user32.mouse_event(down, 0, 0, 0, 0)
        self._user32.mouse_event(up, 0, 0, 0, 0)

    def type_text(self, text: str, *, interval: float = 0.0) -> None:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        root.destroy()
        self.hotkey("ctrl", "v")
        if interval > 0:
            time.sleep(interval)

    def press(self, key: str) -> None:
        vk = _virtual_key(key)
        self._user32.keybd_event(vk, 0, 0, 0)
        self._user32.keybd_event(vk, 0, 0x0002, 0)

    def hotkey(self, *keys: str) -> None:
        virtual_keys = [_virtual_key(key) for key in keys]
        for vk in virtual_keys:
            self._user32.keybd_event(vk, 0, 0, 0)
        for vk in reversed(virtual_keys):
            self._user32.keybd_event(vk, 0, 0x0002, 0)

    def screenshot(self) -> Any:
        raise NotImplementedError("Captura de tela pertence ao módulo de percepção")


def _virtual_key(key: str) -> int:
    normalized = key.casefold().strip()
    aliases = {
        "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B,
        "space": 0x20, "tab": 0x09, "backspace": 0x08,
        "ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12,
        "win": 0x5B, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
        "delete": 0x2E, "home": 0x24, "end": 0x23,
    }
    if normalized in aliases:
        return aliases[normalized]
    if len(normalized) == 1:
        return ord(normalized.upper())
    if normalized.startswith("f") and normalized[1:].isdigit():
        number = int(normalized[1:])
        if 1 <= number <= 12:
            return 0x70 + number - 1
    raise ValueError(f"Tecla não suportada: {key}")
