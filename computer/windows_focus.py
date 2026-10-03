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


def set_clipboard_text(text: str) -> bool:
    """Coloca texto (com acentos) na área de transferência do Windows."""
    if not IS_WINDOWS:
        return False
    import ctypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    data = (text + "\0").encode("utf-16-le")
    for _ in range(5):
        if user32.OpenClipboard(0):
            break
        time.sleep(0.05)
    else:
        return False
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(0x0042, len(data))  # GMEM_MOVEABLE | GMEM_ZEROINIT
        pointer = kernel32.GlobalLock(handle)
        ctypes.memmove(pointer, data, len(data))
        kernel32.GlobalUnlock(handle)
        user32.SetClipboardData(13, handle)  # CF_UNICODETEXT
        return True
    finally:
        user32.CloseClipboard()


def _keys(*codes: int) -> None:
    import ctypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    for code in codes:
        user32.keybd_event(code, 0, 0, 0)
    for code in reversed(codes):
        user32.keybd_event(code, 0, 0x0002, 0)
    time.sleep(0.08)


def navigate_window(fragment: str, url: str) -> bool:
    """Leva a aba ativa da janela (ex.: a do YouTube) para outro endereço, sem abrir página nova."""
    if not IS_WINDOWS or not has_window(fragment) or not focus_window(fragment):
        return False
    if not set_clipboard_text(url):
        return False
    _keys(0x11, 0x4C)  # Ctrl+L: barra de endereço
    time.sleep(0.15)
    _keys(0x11, 0x56)  # Ctrl+V
    time.sleep(0.1)
    _keys(0x0D)  # Enter
    return True


HUD_TITLE = "TELEX"  # a aba da interface ("TELEX — NEURAL CORE")


def close_tab(fragment: str, attempts: int = 4) -> int:
    """Fecha só as abas cujo título tem `fragment` (ex.: YouTube). Nunca a do TELEX.

    A aba precisa estar ativa para o Windows mostrar o título; se não estiver,
    usa a busca de abas do Chrome (Ctrl+Shift+A) para trazê-la. Devolve quantas fechou.
    """
    if not IS_WINDOWS:
        return 0
    closed = 0
    wanted = _plain(fragment)
    for _ in range(attempts):
        target = next(
            (hwnd for hwnd, title in _windows() if wanted in _plain(title) and HUD_TITLE.casefold() not in title.casefold()),
            None,
        )
        if target is None:
            # Talvez esteja numa aba de fundo: a busca de abas do Chrome a ativa.
            chrome = next((hwnd for hwnd, title in _windows() if title.endswith("Google Chrome")), None)
            if chrome is None or closed:
                break
            _focus_hwnd(chrome)
            _keys(0x11, 0x10, 0x41)  # Ctrl+Shift+A
            time.sleep(0.5)
            if not set_clipboard_text(fragment):
                break
            _keys(0x11, 0x56)
            time.sleep(0.5)
            _keys(0x0D)
            time.sleep(0.8)
            target = next(
                (hwnd for hwnd, title in _windows() if wanted in _plain(title) and HUD_TITLE.casefold() not in title.casefold()),
                None,
            )
            if target is None:
                _keys(0x1B)  # fecha a busca
                break
        _focus_hwnd(target)
        _keys(0x11, 0x57)  # Ctrl+W: fecha só a aba ativa
        time.sleep(0.6)
        closed += 1
    return closed


def close_browser_windows(keep_fragment: str = HUD_TITLE) -> int:
    """Fecha as janelas do Chrome, menos a da interface do TELEX."""
    if not IS_WINDOWS:
        return 0
    import ctypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    count = 0
    for hwnd, title in _windows():
        if title.endswith("Google Chrome") and keep_fragment.casefold() not in title.casefold():
            user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
            count += 1
    return count


def _focus_hwnd(hwnd: int) -> None:
    import ctypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, 0x0002, 0)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.25)


def open_in_current_chrome(url: str) -> bool:
    """Abre `url` numa aba nova da janela do Chrome que o Du está usando (logo, no perfil dele agora).

    A janela mais recente (ordem do Windows) que não seja a interface do TELEX.
    """
    if not IS_WINDOWS:
        return False
    target = next(
        (hwnd for hwnd, title in _windows() if title.endswith("Google Chrome") and HUD_TITLE.casefold() not in title.casefold()),
        None,
    ) or next((hwnd for hwnd, title in _windows() if title.endswith("Google Chrome")), None)
    if target is None or not set_clipboard_text(url):
        return False
    _focus_hwnd(target)
    _keys(0x11, 0x54)  # Ctrl+T: aba nova nesta janela/perfil
    time.sleep(0.4)
    _keys(0x11, 0x56)
    time.sleep(0.1)
    _keys(0x0D)
    return True
