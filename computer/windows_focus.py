"""Janelas do Windows: listar títulos, esperar uma janela aparecer e trazê-la para a frente.

Serve de evidência real ("o YouTube abriu mesmo?") e de base para automações
que precisam da janela certa em foco (WhatsApp). Fora do Windows, as funções
devolvem vazio/False e não fazem nada.
"""

from __future__ import annotations

import platform
import time
import unicodedata
from typing import Callable

IS_WINDOWS = platform.system() == "Windows"


def _plain(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", (text or "").casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _windows() -> list[tuple[int, str]]:
    if not IS_WINDOWS:
        return []
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    found: list[tuple[int, str]] = []
    callback_type = getattr(ctypes, "WINFUNCTYPE")(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def collect(hwnd: int, _lparam: int) -> bool:
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                found.append((int(hwnd), buffer.value))
        return True

    user32.EnumWindows(callback_type(collect), 0)
    return found


def window_titles() -> list[str]:
    return [title for _hwnd, title in _windows()]


def has_window(fragment: str, titles: Callable[[], list[str]] = window_titles) -> bool:
    wanted = _plain(fragment)
    return any(wanted in _plain(title) for title in titles())


def wait_for_window(
    fragment: str,
    timeout: float = 8.0,
    *,
    titles: Callable[[], list[str]] = window_titles,
    sleep: Callable[[float], None] = time.sleep,
    step: float = 0.4,
) -> bool:
    """Espera aparecer uma janela cujo título contenha `fragment` (sem acento/caixa).

    Fora do Windows não há janelas para conferir: considera que abriu.
    """
    if not IS_WINDOWS and titles is window_titles:
        return True
    waited = 0.0
    while True:
        if has_window(fragment, titles):
            return True
        if waited >= timeout:
            return False
        sleep(step)
        waited += step


def focus_window(fragment: str) -> bool:
    """Traz para a frente a janela cujo título contém `fragment`."""
    if not IS_WINDOWS:
        return False
    import ctypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    wanted = _plain(fragment)
    for hwnd, title in _windows():
        if wanted in _plain(title):
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            # O Windows só deixa trocar o foco se a última tecla foi "nossa": um ALT solto resolve.
            user32.keybd_event(0x12, 0, 0, 0)
            user32.keybd_event(0x12, 0, 0x0002, 0)
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.25)
            return int(user32.GetForegroundWindow()) == hwnd
    return False
