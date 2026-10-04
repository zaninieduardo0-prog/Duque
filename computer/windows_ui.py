from __future__ import annotations

import ctypes
import platform
import time
from typing import Any, Callable

from .ui import UIController

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
INPUT_KEYBOARD = 1

VK_SHIFT, VK_CONTROL, VK_MENU, VK_RETURN, VK_TAB = 0x10, 0x11, 0x12, 0x0D, 0x09

# Teclas "estendidas": sem a flag, setas/Delete/Home viram as do teclado numérico.
EXTENDED_KEYS = frozenset({
    0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E,  # PgUp PgDn End Home setas Insert Delete
    0x5B, 0x5C, 0x5D, 0x6F, 0x90, 0xA3, 0xA5, 0x2C,  # Win, Apps, Num /, NumLock, Ctrl/Alt direitos, PrintScreen
})

ALIASES: dict[str, int] = {
    "enter": VK_RETURN, "return": VK_RETURN, "esc": 0x1B, "escape": 0x1B,
    "space": 0x20, "espaço": 0x20, "espaco": 0x20, "tab": VK_TAB, "backspace": 0x08,
    "ctrl": VK_CONTROL, "control": VK_CONTROL, "shift": VK_SHIFT, "alt": VK_MENU, "altgr": 0xA5,
    "win": 0x5B, "windows": 0x5B, "super": 0x5B, "cmd": 0x5B, "meta": 0x5B,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "esquerda": 0x25, "cima": 0x26, "direita": 0x27, "baixo": 0x28,
    "delete": 0x2E, "del": 0x2E, "insert": 0x2D, "ins": 0x2D, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pgup": 0x21, "page up": 0x21, "pagedown": 0x22, "pgdn": 0x22, "page down": 0x22,
    "capslock": 0x14, "caps lock": 0x14, "numlock": 0x90, "printscreen": 0x2C, "print screen": 0x2C, "prtsc": 0x2C,
    "apps": 0x5D, "menu": 0x5D, "pause": 0x13,
    "volumeup": 0xAF, "volumedown": 0xAE, "volumemute": 0xAD,
    "playpause": 0xB3, "nexttrack": 0xB0, "prevtrack": 0xB1,
}

# Pontuação no layout americano (usada fora do Windows e quando VkKeyScan não responde).
# Antes, ord(",") virava VK_SNAPSHOT (Print Screen), "." virava Delete, "/" virava Help.
_US_PUNCTUATION: dict[str, tuple[int, bool]] = {
    ";": (0xBA, False), ":": (0xBA, True), "=": (0xBB, False), "+": (0xBB, True),
    ",": (0xBC, False), "<": (0xBC, True), "-": (0xBD, False), "_": (0xBD, True),
    ".": (0xBE, False), ">": (0xBE, True), "/": (0xBF, False), "?": (0xBF, True),
    "`": (0xC0, False), "~": (0xC0, True), "[": (0xDB, False), "{": (0xDB, True),
    "\\": (0xDC, False), "|": (0xDC, True), "]": (0xDD, False), "}": (0xDD, True),
    "'": (0xDE, False), '"': (0xDE, True),
    "!": (0x31, True), "@": (0x32, True), "#": (0x33, True), "$": (0x34, True), "%": (0x35, True),
    "^": (0x36, True), "&": (0x37, True), "*": (0x38, True), "(": (0x39, True), ")": (0x30, True),
}


def key_stroke(key: str, scan: Callable[[str], int] | None = None) -> tuple[int, bool]:
    """Tecla virtual de `key` e se precisa de Shift. ``scan`` é o VkKeyScanW do Windows (layout do Du)."""
    normalized = key.casefold().strip() if len(key.strip()) != 0 else key
    if normalized in ALIASES:
        return ALIASES[normalized], False
    if normalized == " ":
        return 0x20, False
    if len(normalized) == 1:
        char = normalized
        if char.isascii() and char.isalnum():
            return ord(char.upper()), False
        if scan is not None:
            result = scan(char)
            # 0xFFFF: o layout não tem a tecla; bits 0x600: precisa de Ctrl/AltGr (não dá para "apertar").
            if result not in (-1, 0xFFFF) and (result & 0xFF) != 0xFF and not result & 0x600:
                return result & 0xFF, bool(result & 0x100)
        if char in _US_PUNCTUATION:
            return _US_PUNCTUATION[char]
        raise ValueError(f"Tecla não suportada: {key}")
    if normalized.startswith("f") and normalized[1:].isdigit():
        number = int(normalized[1:])
        if 1 <= number <= 24:
            return 0x70 + number - 1, False
    raise ValueError(f"Tecla não suportada: {key}")


def _virtual_key(key: str) -> int:
    return key_stroke(key)[0]


def text_units(text: str) -> list[tuple[str, int]]:
    """Plano de digitação: ("unicode", unidade UTF-16) ou ("vk", tecla) para Enter/Tab.

    Quebra de linha vira Shift+Enter ("shift_enter"): no Bloco de Notas é uma
    linha nova, e no WhatsApp/chats não ENVIA a mensagem pela metade.
    """
    plan: list[tuple[str, int]] = []
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    for char in normalized:
        if char == "\n":
            plan.append(("shift_enter", VK_RETURN))
        elif char == "\t":
            plan.append(("vk", VK_TAB))
        else:
            data = char.encode("utf-16-le")
            for index in range(0, len(data), 2):
                plan.append(("unicode", int.from_bytes(data[index:index + 2], "little")))
    return plan


if platform.system() == "Windows":
    from ctypes import wintypes

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]

    class _INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


class WindowsUIController(UIController):
    """Backend Windows sem dependências externas para mouse/teclado básicos."""

    def __init__(self) -> None:
        if platform.system() != "Windows":
            raise RuntimeError("WindowsUIController requer Windows")
        self._user32 = getattr(ctypes, "windll").user32
        self._user32.VkKeyScanW.argtypes = [ctypes.c_wchar]
        self._user32.VkKeyScanW.restype = ctypes.c_short

    def click(self, x: int, y: int, *, button: str = "left") -> None:
        events = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010), "middle": (0x0020, 0x0040)}
        if button not in events:
            raise ValueError(f"Botão não suportado: {button}")
        self._user32.SetCursorPos(int(x), int(y))
        time.sleep(0.02)
        down, up = events[button]
        self._user32.mouse_event(down, 0, 0, 0, 0)
        self._user32.mouse_event(up, 0, 0, 0, 0)

    # teclado -------------------------------------------------------------------
    def _send(self, items: list[tuple[int, int, int]]) -> None:
        """items: (vk, scan, flags). Usa SendInput (atômico) em vez de keybd_event solto."""
        if not items:
            return
        array = (_INPUT * len(items))()
        for index, (vk, scan, flags) in enumerate(items):
            array[index].type = INPUT_KEYBOARD
            array[index].u.ki = _KEYBDINPUT(vk, scan, flags, 0, 0)
        sent = self._user32.SendInput(len(items), array, ctypes.sizeof(_INPUT))
        if sent != len(items):
            raise RuntimeError("O Windows bloqueou a digitação (janela de administrador em foco?)")

    def _key_flags(self, vk: int) -> int:
        return KEYEVENTF_EXTENDEDKEY if vk in EXTENDED_KEYS else 0

    def type_text(self, text: str, *, interval: float = 0.0) -> None:
        """Digita o texto como caracteres Unicode (acentos e emoji), sem usar a área de transferência.

        Antes colava pelo tkinter: criava uma janela Tk fora da thread principal
        (instável) e apagava o que o Du tinha copiado.
        """
        for kind, value in text_units(text):
            if kind == "unicode":
                self._send([(0, value, KEYEVENTF_UNICODE), (0, value, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)])
            elif kind == "shift_enter":
                self._send([(VK_SHIFT, 0, 0), (VK_RETURN, 0, 0), (VK_RETURN, 0, KEYEVENTF_KEYUP), (VK_SHIFT, 0, KEYEVENTF_KEYUP)])
            else:
                self._send([(value, 0, 0), (value, 0, KEYEVENTF_KEYUP)])
            if interval > 0:
                time.sleep(interval)
            else:
                time.sleep(0.002)

    def _stroke(self, key: str) -> tuple[int, bool]:
        return key_stroke(key, scan=lambda char: int(self._user32.VkKeyScanW(char)) & 0xFFFF)

    def press(self, key: str) -> None:
        vk, shift = self._stroke(key)
        items: list[tuple[int, int, int]] = [(VK_SHIFT, 0, 0)] if shift else []
        items += [(vk, 0, self._key_flags(vk)), (vk, 0, self._key_flags(vk) | KEYEVENTF_KEYUP)]
        if shift:
            items.append((VK_SHIFT, 0, KEYEVENTF_KEYUP))
        self._send(items)

    def hotkey(self, *keys: str) -> None:
        strokes = [self._stroke(key) for key in keys]
        virtual_keys: list[int] = []
        if any(shift for _vk, shift in strokes) and VK_SHIFT not in {vk for vk, _s in strokes}:
            virtual_keys.append(VK_SHIFT)
        virtual_keys += [vk for vk, _shift in strokes]
        down = [(vk, 0, self._key_flags(vk)) for vk in virtual_keys]
        up = [(vk, 0, self._key_flags(vk) | KEYEVENTF_KEYUP) for vk in reversed(virtual_keys)]
        self._send(down + up)

    def screenshot(self) -> Any:
        raise NotImplementedError("Captura de tela pertence ao módulo de percepção")
