from __future__ import annotations

import ctypes
import os
import time
from typing import Any, Callable

from .ui import UIController

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_RETURN = 0x0D
VK_TAB = 0x09

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77

_ALIASES: dict[str, int] = {
    "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B,
    "space": 0x20, "tab": 0x09, "backspace": 0x08,
    "ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12,
    "win": 0x5B, "windows": 0x5B,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "delete": 0x2E, "del": 0x2E, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pgup": 0x21, "page up": 0x21,
    "pagedown": 0x22, "pgdn": 0x22, "page down": 0x22,
    "insert": 0x2D, "ins": 0x2D,
    "capslock": 0x14, "caps lock": 0x14,
    "printscreen": 0x2C, "print screen": 0x2C, "prtsc": 0x2C,
}

# Teclas que o Windows só interpreta corretamente com KEYEVENTF_EXTENDEDKEY
# (setas e o bloco Insert/Home/PageUp/Delete/End/PageDown).
_EXTENDED_KEYS = frozenset({0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E})

# Bits do byte alto de VkKeyScanW -> tecla modificadora necessária.
_SHIFT_STATE_MODIFIERS = ((0x01, VK_SHIFT), (0x02, VK_CONTROL), (0x04, VK_MENU))


class KeySpec:
    """Tecla virtual, modificadoras exigidas pelo layout e flag de tecla estendida."""

    __slots__ = ("vk", "modifiers", "extended")

    def __init__(self, vk: int, modifiers: tuple[int, ...] = (), extended: bool = False) -> None:
        self.vk = vk
        self.modifiers = modifiers
        self.extended = extended

    def __eq__(self, other: object) -> bool:
        return isinstance(other, KeySpec) and (self.vk, self.modifiers, self.extended) == (other.vk, other.modifiers, other.extended)

    def __repr__(self) -> str:
        return f"KeySpec(vk={self.vk:#x}, modifiers={self.modifiers}, extended={self.extended})"


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_int32),
        ("dy", ctypes.c_int32),
        ("mouseData", ctypes.c_uint32),
        ("dwFlags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_uint16),
        ("wScan", ctypes.c_uint16),
        ("dwFlags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_uint32),
        ("wParamL", ctypes.c_uint16),
        ("wParamH", ctypes.c_uint16),
    ]


class _INPUTUNION(ctypes.Union):
    # MOUSEINPUT é o maior membro: mantém sizeof(INPUT) = 40 em 64 bits / 28 em 32 bits.
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("union", _INPUTUNION)]


def _keyboard_input(vk: int = 0, scan: int = 0, flags: int = 0) -> _INPUT:
    item = _INPUT()
    item.type = INPUT_KEYBOARD
    item.union.ki = _KEYBDINPUT(vk, scan, flags, 0, 0)
    return item


_dpi_configured = False


def ensure_dpi_awareness() -> None:
    """Faz o processo usar pixels físicos, alinhando captura de tela e cliques."""
    global _dpi_configured
    if _dpi_configured or os.name != "nt":
        return
    _dpi_configured = True
    windll = getattr(ctypes, "windll")
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 (Windows 10 1703+).
        if windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except (AttributeError, OSError):
        pass
    try:
        windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except (AttributeError, OSError):
        pass


class WindowsUIController(UIController):
    """Backend Windows sem dependências externas para mouse/teclado básicos."""

    _user32: Any

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("WindowsUIController requer Windows")
        ensure_dpi_awareness()
        self._user32 = getattr(ctypes, "WinDLL")("user32", use_last_error=True)
        self._user32.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(_INPUT), ctypes.c_int]
        self._user32.SendInput.restype = ctypes.c_uint
        self._user32.VkKeyScanW.argtypes = [ctypes.c_wchar]
        self._user32.VkKeyScanW.restype = ctypes.c_short

    def click(self, x: int, y: int, *, button: str = "left") -> None:
        events = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010), "middle": (0x0020, 0x0040)}
        if button not in events:
            raise ValueError(f"Botão não suportado: {button}")
        # A captura (all_screens) começa no canto da tela virtual, que pode ser
        # negativo com monitores à esquerda/acima do principal.
        left = int(self._user32.GetSystemMetrics(SM_XVIRTUALSCREEN))
        top = int(self._user32.GetSystemMetrics(SM_YVIRTUALSCREEN))
        if not self._user32.SetCursorPos(int(x) + left, int(y) + top):
            raise OSError(_last_error(), "SetCursorPos falhou")
        down, up = events[button]
        self._user32.mouse_event(down, 0, 0, 0, 0)
        self._user32.mouse_event(up, 0, 0, 0, 0)

    def type_text(self, text: str, *, interval: float = 0.0) -> None:
        """Digita via KEYEVENTF_UNICODE: não usa nem altera a área de transferência."""
        data = text.replace("\r\n", "\n").encode("utf-16-le")
        units = [int.from_bytes(data[index:index + 2], "little") for index in range(0, len(data), 2)]
        for unit in units:
            if unit == 0x0A:
                inputs = [_keyboard_input(VK_RETURN), _keyboard_input(VK_RETURN, flags=KEYEVENTF_KEYUP)]
            elif unit == 0x09:
                inputs = [_keyboard_input(VK_TAB), _keyboard_input(VK_TAB, flags=KEYEVENTF_KEYUP)]
            else:
                # Pares substitutos (emoji etc.) vão como duas unidades UTF-16 em sequência.
                inputs = [
                    _keyboard_input(scan=unit, flags=KEYEVENTF_UNICODE),
                    _keyboard_input(scan=unit, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP),
                ]
            self._send(inputs)
            if interval > 0:
                time.sleep(interval)

    def press(self, key: str) -> None:
        self.hotkey(key)

    def hotkey(self, *keys: str) -> None:
        specs = [_virtual_key(key, self._vk_scan) for key in keys]
        sequence: list[tuple[int, bool]] = []
        for spec in specs:
            for modifier in spec.modifiers:
                if all(vk != modifier for vk, _ in sequence):
                    sequence.append((modifier, False))
            sequence.append((spec.vk, spec.extended))
        downs = [_keyboard_input(vk, flags=KEYEVENTF_EXTENDEDKEY if extended else 0) for vk, extended in sequence]
        ups = [
            _keyboard_input(vk, flags=KEYEVENTF_KEYUP | (KEYEVENTF_EXTENDEDKEY if extended else 0))
            for vk, extended in reversed(sequence)
        ]
        self._send(downs + ups)

    def _vk_scan(self, char: str) -> int:
        return int(self._user32.VkKeyScanW(char))

    def _send(self, inputs: list[_INPUT]) -> None:
        array = (_INPUT * len(inputs))(*inputs)
        sent = self._user32.SendInput(len(inputs), array, ctypes.sizeof(_INPUT))
        if sent != len(inputs):
            # Normalmente UIPI: a janela em foco roda como administrador.
            raise OSError(_last_error(), "SendInput bloqueado pelo Windows")


def _last_error() -> int:
    return int(getattr(ctypes, "get_last_error")())


def _virtual_key(key: str, vk_scan: Callable[[str], int] | None = None) -> KeySpec:
    """Traduz o nome de uma tecla; pontuação usa o layout atual via VkKeyScanW."""
    normalized = " ".join(key.casefold().split())
    if normalized in _ALIASES:
        vk = _ALIASES[normalized]
        return KeySpec(vk, extended=vk in _EXTENDED_KEYS)
    if normalized.startswith("f") and normalized[1:].isdigit():
        number = int(normalized[1:])
        if 1 <= number <= 24:
            return KeySpec(0x70 + number - 1)
    char = key if len(key) == 1 else normalized
    if len(char) == 1:
        if char.isascii() and char.isalnum():
            return KeySpec(ord(char.upper()))
        if vk_scan is not None:
            result = int(vk_scan(char)) & 0xFFFF
            if result != 0xFFFF:
                state = (result >> 8) & 0xFF
                modifiers = tuple(vk for bit, vk in _SHIFT_STATE_MODIFIERS if state & bit)
                return KeySpec(result & 0xFF, modifiers)
    raise ValueError(f"Tecla não suportada: {key}")
