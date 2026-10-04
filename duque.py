from __future__ import annotations

import logging
import os
import sys
import threading
import time
import urllib.request
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

os.environ.setdefault("DUQUE_WORKSPACE_ROOT", str(ROOT))
os.environ.setdefault("DUQUE_AUTONOMOUS_AGENT", "1")
os.environ.setdefault("DUQUE_PITCH", "-2.0")
os.environ.setdefault("DUQUE_VOICE_SPEED", "0.96")
os.environ.setdefault("DUQUE_VOICE_PROCESSING", "0")

LOG_PATH = ROOT / "duque.log"
LOG_MAX_BYTES = 5 * 1024 * 1024


def rotate_log(path: Path = LOG_PATH, max_bytes: int = LOG_MAX_BYTES) -> None:
    """O duque.log crescia para sempre; acima do limite vira duque.log.1 (só uma cópia)."""
    try:
        if path.exists() and path.stat().st_size > max_bytes:
            path.replace(path.with_name(path.name + ".1"))
    except OSError:
        pass  # outro programa com o arquivo aberto (Windows): tenta no próximo início


rotate_log()
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


# Tempo para uma aba do HUD que já estava aberta (antes de um reinício pela
# Forja/supervisor) se reconectar sozinha antes de abrirmos outra.
HUD_RECONNECT_GRACE = float(os.getenv("DUQUE_HUD_GRACE", "8") or 8)


def open_interface(wait_server: bool = True, grace: float = HUD_RECONNECT_GRACE) -> None:
    # Iniciou com o Windows em modo oculto: não abre o HUD agora; ele abre
    # sozinho quando o Du ativar a voz (ver duque_wake_v2.abrir_interface_na_ativacao).
    if start_hidden():
        mark("modo oculto: HUD abre só na ativação por voz")
        return
    # Abre o HUD assim que o servidor responder (antes: espera fixa + voz carregada).
    deadline = time.monotonic() + 30
    while wait_server and not server_online() and time.monotonic() < deadline:
        time.sleep(0.15)
    mark("servidor respondendo; conferindo a interface")
    try:
        from core.hud import abrir_hud

        # Só abre se nenhuma aba do HUD estiver conectada: antes cada início,
        # reinício ou segunda abertura criava mais uma aba no Chrome.
        if abrir_hud(URL, esperar_reconexao=grace, log=lambda text: print(text, flush=True)):
            mark("interface aberta")
    except Exception as exc:
        print(f"[DUQUE] Não consegui abrir a interface automaticamente: {exc}", flush=True)


CORE_READY = threading.Event()


def load_voice():
    """Carrega a voz (modelos de ativação, áudio, OpenAI Realtime) logo depois do núcleo,
    com o servidor já no ar: o HUD e o texto funcionam enquanto isso."""
    CORE_READY.wait(120)
    try:
        import duque_wake_v2 as voice_runtime  # runtime único de voz (o v3 virou só um apelido)
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


INSTANCE_LOCK: object | None = None  # mantida viva enquanto o processo roda


def main() -> None:
    global INSTANCE_LOCK
    # Se o servidor já está ativo, esta é uma segunda tentativa de inicialização.
    # Não importamos o servidor/agente novamente para evitar duplicar scheduler e estado.
    if server_online():
        print("[DUQUE] Instância já ativa; mostrando a interface se ela estiver fechada.", flush=True)
        open_interface(wait_server=False, grace=0)
        return

    # Trava do sistema operacional: duas aberturas quase juntas não sobem dois
    # núcleos (dois agendadores repetindo os mesmos lembretes e ações).
    from core.instance import InstanceLock

    lock = InstanceLock(ROOT / "duque_data" / "duque.lock")
    if not lock.acquire():
        print("[DUQUE] Outra instância já está iniciando; só mostro a interface.", flush=True)
        open_interface(wait_server=True, grace=0)
        return
    INSTANCE_LOCK = lock

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
    print('Voz: "TELEX" + conversa Realtime', flush=True)
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
