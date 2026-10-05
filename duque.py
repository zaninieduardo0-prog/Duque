from __future__ import annotations

import logging
import os
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path


ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

from core.windows import hide_console_windows  # noqa: E402

# Nenhum comando em segundo plano (Spotify, git, abrir apps) pisca janela de CMD.
hide_console_windows()

# Pixels do print = pixels do mouse, mesmo com a escala do Windows em 125%/150%
# (sem isso, "clique no botão X" acertaria o lugar errado).
if sys.platform.startswith("win"):
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # type: ignore[attr-defined]
    except Exception:
        pass


_SINGLE_INSTANCE_HANDLE = None
_SINGLE_INSTANCE_NAME = "Local\\Duque_TELEX_SingleInstance"


def acquire_single_instance() -> bool:
    """Impede duas instâncias do núcleo de rodarem ao mesmo tempo no Windows.

    A checagem HTTP sozinha tem uma condição de corrida: duas inicializações
    simultâneas podem verificar /status antes de qualquer uma abrir a porta.
    O mutex nomeado fecha essa brecha e também protege contra múltiplos
    lançadores (PowerShell, VBS, supervisor ou atalho do Windows).
    """
    global _SINGLE_INSTANCE_HANDLE
    if not sys.platform.startswith("win"):
        return True
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.GetLastError.restype = wintypes.DWORD
        handle = kernel32.CreateMutexW(None, True, _SINGLE_INSTANCE_NAME)
        if not handle:
            return False
        ERROR_ALREADY_EXISTS = 183
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        _SINGLE_INSTANCE_HANDLE = handle
        return True
    except Exception:
        # Se a API de mutex não estiver disponível, mantém o comportamento
        # anterior baseado em /status em vez de impedir a inicialização.
        return True


os.environ.setdefault("DUQUE_WORKSPACE_ROOT", str(ROOT))
os.environ.setdefault("DUQUE_AUTONOMOUS_AGENT", "1")
os.environ.setdefault("DUQUE_PITCH", "-2.0")
os.environ.setdefault("DUQUE_VOICE_SPEED", "0.96")
os.environ.setdefault("DUQUE_VOICE_PROCESSING", "0")

LOG_PATH = ROOT / "duque.log"
LOG_FILE = LOG_PATH.open("a", encoding="utf-8", buffering=1)
sys.stdout = LOG_FILE
sys.stderr = LOG_FILE

# Diagnóstico de quedas: qualquer erro não tratado (inclusive em threads e falhas
# nativas de áudio) fica registrado no duque.log com a pilha completa.
import faulthandler  # noqa: E402
import traceback  # noqa: E402

faulthandler.enable(file=LOG_FILE, all_threads=True)


def _log_crash(kind: str, exc_type, exc, tb) -> None:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] [QUEDA] {kind}: {exc_type.__name__}: {exc}\n{''.join(traceback.format_tb(tb))}", flush=True)


sys.excepthook = lambda t, e, tb: _log_crash("processo", t, e, tb)
threading.excepthook = lambda args: _log_crash(
    f"thread {args.thread.name if args.thread else '?'}", args.exc_type, args.exc_value, args.exc_traceback
)


URL = "http://127.0.0.1:5000"


def server_online() -> bool:
    try:
        with urllib.request.urlopen(f"{URL}/status", timeout=0.7) as response:
            return response.status == 200
    except Exception:
        return False


STARTED = time.monotonic()


def mark(step: str) -> None:
    """Linha de tempo da inicialização no duque.log (para achar o que demora)."""
    print(f"[INÍCIO] {step} em {time.monotonic() - STARTED:.1f}s", flush=True)


def start_hidden() -> bool:
    return os.getenv("DUQUE_START_HIDDEN", "0").casefold() in {"1", "true", "yes", "on", "sim"}


def open_interface(wait_server: bool = True) -> None:
    # Iniciou com o Windows em modo oculto: não abre o HUD agora; ele abre
    # sozinho quando o Du ativar a voz (ver duque_wake_v2.abrir_interface_na_ativacao).
    if start_hidden():
        mark("modo oculto: HUD abre só na ativação por voz")
        return
    # Abre o HUD assim que o servidor responder (antes: espera fixa + voz carregada).
    deadline = time.monotonic() + 30
    while wait_server and not server_online() and time.monotonic() < deadline:
        time.sleep(0.15)
    mark("servidor respondendo; abrindo a interface")
    try:
        from computer.chrome import open_in_chrome

        # Chrome no perfil do Du (sem a tela de escolher conta); senão, o navegador padrão.
        if not open_in_chrome(URL):
            webbrowser.open_new_tab(URL)
    except Exception as exc:
        print(f"[DUQUE] Não consegui abrir a interface automaticamente: {exc}", flush=True)


CORE_READY = threading.Event()


def load_voice():
    """Carrega a voz (modelos de ativação, áudio, OpenAI Realtime) logo depois do núcleo,
    com o servidor já no ar: o HUD e o texto funcionam enquanto isso."""
    CORE_READY.wait(120)
    try:
        import duque_wake_v3 as voice_runtime
    except BaseException as exc:
        import traceback

        print(f"[VOZ] não carregou: {type(exc).__name__}: {exc!r}\n{traceback.format_exc()}", flush=True)
        return None
    mark("voz carregada")
    return voice_runtime


def start_voice(voice_runtime=None) -> None:
    if voice_runtime is None:
        voice_runtime = load_voice()
        if voice_runtime is None:
            return
    try:
        voice_runtime.log("TELEX integrado: iniciando ativação por voz + conversa.")
        voice_runtime.wake_loop()
    except BaseException as exc:  # SystemExit também: antes a voz morria sem deixar rastro
        import traceback

        voice_runtime.log(
            f"Falha fatal no runtime de voz: {type(exc).__name__}: {exc!r}\n{traceback.format_exc()}"
        )


def keep_process_alive() -> None:
    while True:
        time.sleep(60)


def main() -> None:
    # O mutex vem antes do servidor e antes das threads para impedir qualquer
    # duplicação de núcleo mesmo quando dois lançadores iniciam quase juntos.
    if not acquire_single_instance():
        print("[DUQUE] Instância já ativa; encerrando esta inicialização duplicada.", flush=True)
        return

    # Se o servidor já está ativo, esta é uma segunda tentativa de inicialização.
    # Não importamos o servidor/agente novamente para evitar duplicar scheduler e estado.
    if server_online():
        print("[DUQUE] Instância já ativa; abrindo a interface.", flush=True)
        open_interface(wait_server=False)
        return

    # Voz carrega em paralelo, logo depois do núcleo (sem disputar as mesmas importações).
    threading.Thread(target=start_voice, name="duque-voice", daemon=True).start()
    threading.Thread(target=open_interface, name="duque-interface", daemon=True).start()

    # Só carregamos o servidor/agente depois da checagem de instância única.
    # Assim uma segunda abertura não cria outro AgentLoop nem outro scheduler.
    from servidor import app

    mark("núcleo carregado")
    CORE_READY.set()

    print("=" * 64, flush=True)
    print(f"TELEX — SISTEMA INTEGRADO ({time.strftime('%Y-%m-%d %H:%M:%S')})", flush=True)
    print("=" * 64, flush=True)
    print(f"Workspace: {ROOT}", flush=True)
    print("Texto: interface + /api/comando", flush=True)
    print('Voz: "Bom dia, TELEX" / "Telex" + conversa Realtime', flush=True)
    print("Autonomia: habilitada", flush=True)

    print("[DUQUE] Servidor ainda não estava ativo; iniciando agora.", flush=True)

    print("=" * 64, flush=True)

    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
        threaded=True,
        use_reloader=False,
    )


if __name__ == "__main__":
    main()
