"""Abre a interface (HUD) só quando ela ainda não está aberta.

Antes, cada início do TELEX, cada reinício pelo supervisor (Forja, queda), cada
segunda abertura do Duque.vbs e cada ativação por voz no modo oculto abria mais
uma aba. Agora quem quiser mostrar o HUD chama ``abrir_hud()``: ela pergunta ao
servidor se alguma aba está conectada (``GET /api/hud``, alimentado pela conexão
SSE que cada aba mantém) e, se houver, não abre outra.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
import webbrowser
from typing import Callable

SERVER = "http://127.0.0.1:5000"
# Depois de abrir uma aba, ela leva alguns segundos para conectar; nesse
# intervalo nenhuma outra abertura acontece (launcher + voz ao mesmo tempo).
DEBOUNCE_SECONDS = 25.0

_lock = threading.Lock()
_ultima_abertura = {"em": 0.0}


def hud_conectados(url: str = SERVER, timeout: float = 1.0) -> int | None:
    """Quantas abas do HUD estão conectadas; None se o servidor não respondeu."""
    try:
        with urllib.request.urlopen(f"{url}/api/hud", timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8") or "{}")
        return int(data.get("conectados") or 0)
    except Exception:
        return None


def _abrir_navegador(url: str) -> None:
    try:
        from computer.chrome import open_in_chrome

        # Chrome no perfil do Du (sem a tela de escolher conta); senão, o navegador padrão.
        if open_in_chrome(url):
            return
    except Exception:
        pass
    webbrowser.open_new_tab(url)


def abrir_hud(
    url: str = SERVER,
    *,
    esperar_reconexao: float = 0.0,
    log: Callable[[str], object] = print,
    abrir: Callable[[str], object] | None = None,
    conectados: Callable[[str], int | None] | None = None,
    relogio: Callable[[], float] = time.monotonic,
    dormir: Callable[[float], None] = time.sleep,
) -> bool:
    """Abre o HUD se nenhuma aba estiver conectada. Devolve True se abriu.

    ``esperar_reconexao``: segundos dando chance a uma aba já aberta (de antes de
    um reinício) se reconectar sozinha antes de decidir abrir outra.
    """
    contar = conectados or hud_conectados
    limite = relogio() + max(0.0, esperar_reconexao)
    while True:
        if (contar(url) or 0) > 0:
            log("[HUD] interface já aberta; não abro outra aba.")
            return False
        if relogio() >= limite:
            break
        dormir(0.5)
    with _lock:
        agora = relogio()
        if _ultima_abertura["em"] and agora - _ultima_abertura["em"] < DEBOUNCE_SECONDS:
            log("[HUD] interface aberta há instantes; aguardando ela conectar.")
            return False
        _ultima_abertura["em"] = agora
    try:
        (abrir or _abrir_navegador)(url)
    except Exception as exc:
        log(f"[HUD] não consegui abrir a interface: {type(exc).__name__}: {exc}")
        return False
    return True
