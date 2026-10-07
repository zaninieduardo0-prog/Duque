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


def _is_chrome(title: str) -> bool:
    """Janela do Chrome ("Página - Google Chrome", às vezes seguida do nome do perfil)."""
    return "google chrome" in (title or "").casefold()


def _is_hud(title: str) -> bool:
    return HUD_TITLE.casefold() in (title or "").casefold()


def _focus_hwnd(hwnd: int) -> bool:
    """Traz a janela para a frente e CONFERE: teclas mandadas sem foco iriam para outra janela."""
    if not IS_WINDOWS:
        return False
    import ctypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    # O Windows só deixa trocar o foco se a última tecla foi "nossa": um ALT solto resolve.
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, 0x0002, 0)
    user32.SetForegroundWindow(hwnd)
    for _ in range(6):
        time.sleep(0.05)
        if int(user32.GetForegroundWindow() or 0) == int(hwnd):
            time.sleep(0.15)
            return True
    return False


def focus_window(fragment: str) -> bool:
    """Traz para a frente a janela cujo título contém `fragment` (nunca a interface do TELEX)."""
    if not IS_WINDOWS:
        return False
    wanted = _plain(fragment)
    for hwnd, title in _windows():  # ordem Z: a mais recente primeiro
        if wanted in _plain(title) and (not _is_hud(title) or _is_hud(fragment)):
            return _focus_hwnd(hwnd)
    return False


def _process_image(pid: int) -> str:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ""
        return buffer.value.replace("/", "\\").rsplit("\\", 1)[-1].casefold()
    finally:
        kernel32.CloseHandle(handle)


def focus_process_window(process_names: list[str] | tuple[str, ...]) -> bool:
    """Traz para a frente a janela visível de um destes executáveis (ex.: spotify.exe)."""
    if not IS_WINDOWS:
        return False
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    wanted = {name.casefold() for name in process_names}
    for hwnd, title in _windows():
        if _is_hud(title):
            continue
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            image = _process_image(int(pid.value))
        except Exception:
            continue
        if image in wanted:
            return _focus_hwnd(hwnd)
    return False


def _clipboard_api() -> tuple[object, object]:
    import ctypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user32.GetClipboardData.restype = ctypes.c_void_p
    user32.GetClipboardData.argtypes = [ctypes.c_uint]
    return user32, kernel32


def _open_clipboard(user32: object) -> bool:
    for _ in range(10):
        if user32.OpenClipboard(0):  # type: ignore[attr-defined]
            return True
        time.sleep(0.05)
    return False


def get_clipboard_text() -> str | None:
    """Texto da área de transferência do Windows (None se não houver texto)."""
    if not IS_WINDOWS:
        return None
    import ctypes

    user32, kernel32 = _clipboard_api()
    if not _open_clipboard(user32):
        return None
    try:
        handle = user32.GetClipboardData(13)  # type: ignore[attr-defined]  # CF_UNICODETEXT
        if not handle:
            return None
        pointer = kernel32.GlobalLock(handle)  # type: ignore[attr-defined]
        if not pointer:
            return None
        try:
            return ctypes.wstring_at(pointer)
        finally:
            kernel32.GlobalUnlock(handle)  # type: ignore[attr-defined]
    finally:
        user32.CloseClipboard()  # type: ignore[attr-defined]


def set_clipboard_text(text: str) -> bool:
    """Coloca texto (com acentos) na área de transferência do Windows."""
    if not IS_WINDOWS:
        return False
    import ctypes

    user32, kernel32 = _clipboard_api()
    data = (text + "\0").encode("utf-16-le")
    if not _open_clipboard(user32):
        return False
    try:
        user32.EmptyClipboard()  # type: ignore[attr-defined]
        handle = kernel32.GlobalAlloc(0x0042, len(data))  # type: ignore[attr-defined]  # GMEM_MOVEABLE | GMEM_ZEROINIT
        if not handle:
            return False
        pointer = kernel32.GlobalLock(handle)  # type: ignore[attr-defined]
        if not pointer:
            kernel32.GlobalFree(handle)  # type: ignore[attr-defined]
            return False
        ctypes.memmove(pointer, data, len(data))
        kernel32.GlobalUnlock(handle)  # type: ignore[attr-defined]
        if not user32.SetClipboardData(13, handle):  # type: ignore[attr-defined]  # CF_UNICODETEXT
            kernel32.GlobalFree(handle)  # type: ignore[attr-defined]  # o sistema só fica dono se der certo
            return False
        return True
    finally:
        user32.CloseClipboard()  # type: ignore[attr-defined]


def _paste(text: str) -> bool:
    """Cola `text` (Ctrl+V) e devolve à área de transferência o que o Du tinha copiado."""
    previous = get_clipboard_text()
    if not set_clipboard_text(text):
        return False
    _keys(0x11, 0x56)  # Ctrl+V
    time.sleep(0.25)
    if previous is not None:
        set_clipboard_text(previous)
    return True


def _keys(*codes: int) -> None:
    import ctypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    for code in codes:
        user32.keybd_event(code, 0, 0, 0)
    for code in reversed(codes):
        user32.keybd_event(code, 0, 0x0002, 0)
    time.sleep(0.08)


def navigate_window(fragment: str, url: str) -> bool:
    """Leva a aba ativa da janela (ex.: a do YouTube) para outro endereço, sem abrir página nova.

    Só em janela do Chrome (Ctrl+L numa pasta do Explorer chamada "YouTube" digitaria a URL nela).
    """
    if not IS_WINDOWS:
        return False
    wanted = _plain(fragment)
    target = next((hwnd for hwnd, title in _windows() if wanted in _plain(title) and _is_chrome(title) and not _is_hud(title)), None)
    if target is None or not _focus_hwnd(target):
        return False
    _keys(0x11, 0x4C)  # Ctrl+L: barra de endereço
    time.sleep(0.15)
    if not _paste(url):
        _keys(0x1B)
        return False
    time.sleep(0.1)
    _keys(0x0D)  # Enter
    return True


HUD_TITLE = "TELEX"  # a aba da interface ("TELEX — NEURAL CORE")


def _tab_window(wanted: str) -> int | None:
    return next(
        (hwnd for hwnd, title in _windows() if wanted in _plain(title) and _is_chrome(title) and not _is_hud(title)),
        None,
    )


def close_tab(fragment: str, attempts: int = 4) -> int:
    """Fecha só as abas do Chrome cujo título tem `fragment` (ex.: YouTube). Nunca a do TELEX.

    A aba precisa estar ativa para o Windows mostrar o título; se não estiver,
    usa a busca de abas do Chrome (Ctrl+Shift+A) para trazê-la. Devolve quantas fechou.
    Ctrl+W só é enviado depois de conferir que a janela certa está em foco.
    """
    if not IS_WINDOWS:
        return 0
    closed = 0
    wanted = _plain(fragment)
    for _ in range(attempts):
        target = _tab_window(wanted)
        if target is None:
            # Talvez esteja numa aba de fundo: a busca de abas do Chrome a ativa.
            chrome = next((hwnd for hwnd, title in _windows() if _is_chrome(title) and not _is_hud(title)), None)
            if chrome is None or closed or not _focus_hwnd(chrome):
                break
            _keys(0x11, 0x10, 0x41)  # Ctrl+Shift+A
            time.sleep(0.5)
            if not _paste(fragment):
                _keys(0x1B)
                break
            time.sleep(0.5)
            _keys(0x0D)
            time.sleep(0.8)
            target = _tab_window(wanted)
            if target is None:
                _keys(0x1B)  # fecha a busca
                break
        if not _focus_hwnd(target):
            break
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
        if _is_chrome(title) and keep_fragment.casefold() not in title.casefold():
            user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
            count += 1
    return count


def focus_site(fragment: str) -> bool:
    """Traz a janela do Chrome cuja aba ativa tem `fragment` no título (ex.: "YouTube")."""
    if not IS_WINDOWS:
        return False
    target = _tab_window(_plain(fragment))
    return target is not None and _focus_hwnd(target)


def chrome_window_open() -> bool:
    """Há uma janela do Chrome (fora a do TELEX) aberta?"""
    return any(_is_chrome(title) and not _is_hud(title) for _hwnd, title in _windows())


def focus_chrome() -> bool:
    """Traz para a frente a janela do Chrome mais recente (fora a do TELEX)."""
    target = next((hwnd for hwnd, title in _windows() if _is_chrome(title) and not _is_hud(title)), None)
    return target is not None and _focus_hwnd(target)


def open_in_current_chrome(url: str) -> bool:
    """Abre `url` numa aba nova da janela do Chrome que o Du está usando (logo, no perfil dele agora).

    A janela mais recente (ordem do Windows) que não seja a interface do TELEX.
    """
    if not IS_WINDOWS:
        return False
    target = next(
        (hwnd for hwnd, title in _windows() if _is_chrome(title) and not _is_hud(title)),
        None,
    ) or next((hwnd for hwnd, title in _windows() if _is_chrome(title)), None)
    if target is None or not _focus_hwnd(target):
        return False
    _keys(0x11, 0x54)  # Ctrl+T: aba nova nesta janela/perfil
    time.sleep(0.4)
    if not _paste(url):
        _keys(0x11, 0x57)  # desfaz a aba vazia
        return False
    time.sleep(0.1)
    _keys(0x0D)
    return True
