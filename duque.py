from __future__ import annotations

import json
import logging
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

os.environ.setdefault("DUQUE_WORKSPACE_ROOT", str(ROOT))
os.environ.setdefault("DUQUE_AUTONOMOUS_AGENT", "1")
os.environ.setdefault("DUQUE_VOICE", "cedar")
os.environ.setdefault("DUQUE_PITCH", "-2.0")
os.environ.setdefault("DUQUE_VOICE_SPEED", "0.96")
os.environ.setdefault("DUQUE_VOICE_PROCESSING", "0")
# Token compartilhado entre o servidor e a voz (mesmo processo).
os.environ.setdefault("DUQUE_API_TOKEN", uuid4().hex)

LOG_PATH = ROOT / "duque.log"
LOG_MAX_BYTES = 5 * 1024 * 1024
if LOG_PATH.exists() and LOG_PATH.stat().st_size > LOG_MAX_BYTES:
    # Mantém só o log anterior; sem isso o arquivo cresce para sempre.
    LOG_PATH.replace(LOG_PATH.with_suffix(".log.1"))
LOG_FILE = LOG_PATH.open("a", encoding="utf-8", buffering=1)
sys.stdout = LOG_FILE
sys.stderr = LOG_FILE
logging.basicConfig(level=logging.INFO, stream=LOG_FILE, format="[%(asctime)s] %(name)s: %(message)s")


URL = "http://127.0.0.1:5000"
# Porta usada só como trava de instância única: o sistema operacional libera
# sozinho quando o processo termina, mesmo após uma queda.
LOCK_PORT = 50999


def acquire_instance_lock() -> socket.socket | None:
    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        lock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)  # type: ignore[attr-defined]
    try:
        lock.bind(("127.0.0.1", LOCK_PORT))
        lock.listen(1)
    except OSError:
        lock.close()
        return None
    return lock


def read_status() -> dict | None:
    try:
        with urllib.request.urlopen(f"{URL}/status", timeout=0.7) as response:
            if response.status != 200:
                return None
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def hud_connected() -> bool:
    status = read_status()
    return bool(status and status.get("hud_conectada"))


def open_interface(wait_seconds: float = 0.0) -> None:
    """Abre o HUD só se nenhuma aba dele estiver conectada.

    Cada aba mantém uma conexão aberta com o servidor (/api/hud/stream) e se
    reconecta sozinha em ~2 s depois de um reinício, então abrir outra só
    duplicaria a interface.
    """
    deadline = time.monotonic() + wait_seconds
    while True:
        if hud_connected():
            print("[DUQUE] Interface já aberta; não vou abrir outra.", flush=True)
            return
        if time.monotonic() >= deadline:
            break
        time.sleep(0.5)
    try:
        webbrowser.open_new_tab(URL)
    except Exception as exc:
        print(f"[DUQUE] Não consegui abrir a interface automaticamente: {exc}", flush=True)


def start_voice(voice_runtime) -> None:
    try:
        voice_runtime.log("Duque integrado: iniciando wake word + conversa de voz.")
        voice_runtime.wake_loop()
    except BaseException as exc:
        voice_runtime.log(f"Falha fatal no runtime de voz: {type(exc).__name__}: {exc!r}")
        voice_runtime.hud("erro", f"Voz indisponível: {exc}"[:120], mode="texto")


def main() -> None:
    instance_lock = acquire_instance_lock()
    if instance_lock is None:
        # Outra instância está ativa (ou subindo). Só garante que há uma interface.
        print("[DUQUE] Instância já ativa.", flush=True)
        open_interface(wait_seconds=6.0)
        return

    # Só carregamos o servidor/agente depois da trava de instância única.
    # Assim uma segunda abertura não cria outro AgentLoop nem outra agenda.
    from servidor import app

    try:
        import duque_wake as voice_runtime
    except Exception as exc:
        # Sem microfone/dependências de voz o Duque continua funcionando por texto.
        print(f"[DUQUE] Voz desativada: {type(exc).__name__}: {exc}", flush=True)
        voice_runtime = None

    print("=" * 64, flush=True)
    print("DUQUE — SISTEMA INTEGRADO", flush=True)
    print("=" * 64, flush=True)
    print(f"Workspace: {ROOT}", flush=True)
    print("Texto: interface + /api/comando", flush=True)
    print('Voz: wake word "Hey Jarvis" + conversa Realtime', flush=True)
    print("=" * 64, flush=True)

    if voice_runtime is not None:
        threading.Thread(target=start_voice, args=(voice_runtime,), name="duque-voice", daemon=True).start()
    threading.Thread(target=open_interface, args=(6.0,), name="duque-interface", daemon=True).start()

    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    try:
        app.run(host="127.0.0.1", port=5000, debug=False, threaded=True, use_reloader=False)
    finally:
        instance_lock.close()


if __name__ == "__main__":
    main()
