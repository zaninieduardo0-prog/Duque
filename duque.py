from __future__ import annotations

import json
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

os.environ.setdefault("DUQUE_WORKSPACE_ROOT", str(ROOT))
os.environ.setdefault("DUQUE_AUTONOMOUS_AGENT", "1")
os.environ.setdefault("DUQUE_VOICE", "cedar")
os.environ.setdefault("DUQUE_PITCH", "-2.0")
os.environ.setdefault("DUQUE_VOICE_SPEED", "0.96")
os.environ.setdefault("DUQUE_VOICE_PROCESSING", "0")

LOG_PATH = ROOT / "duque.log"
LOG_FILE = LOG_PATH.open("a", encoding="utf-8", buffering=1)
sys.stdout = LOG_FILE
sys.stderr = LOG_FILE


URL = "http://127.0.0.1:5000"


def read_status() -> dict | None:
    try:
        with urllib.request.urlopen(f"{URL}/status", timeout=0.7) as response:
            if response.status != 200:
                return None
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def server_online() -> bool:
    return read_status() is not None


def hud_connected() -> bool:
    status = read_status()
    return bool(status and status.get("hud_conectada"))


def open_interface(wait_seconds: float = 0.0) -> None:
    """Abre o HUD só se nenhuma aba dele estiver conectada.

    Depois de um reinício (atualização da Forja ou queda), a aba que já estava
    aberta volta a consultar o servidor sozinha; abrir outra só duplicaria.
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
    except Exception as exc:
        voice_runtime.log(
            f"Falha fatal no runtime de voz: {type(exc).__name__}: {exc!r}"
        )


def keep_process_alive() -> None:
    while True:
        time.sleep(60)


def main() -> None:
    # Se o servidor já está ativo, esta é uma segunda tentativa de inicialização.
    # Não importamos o servidor/agente novamente para evitar duplicar scheduler e estado.
    if server_online():
        print("[DUQUE] Instância já ativa.", flush=True)
        open_interface()
        return

    # Só carregamos o servidor/agente depois da checagem de instância única.
    # Assim uma segunda abertura não cria outro AgentLoop nem outro scheduler.
    from servidor import app
    import duque_wake as voice_runtime

    print("=" * 64, flush=True)
    print("DUQUE — SISTEMA INTEGRADO", flush=True)
    print("=" * 64, flush=True)
    print(f"Workspace: {ROOT}", flush=True)
    print("Texto: interface + /api/comando", flush=True)
    print('Voz: wake word "Hey Jarvis" + conversa Realtime', flush=True)
    print("Autonomia: habilitada", flush=True)

    print("[DUQUE] Servidor ainda não estava ativo; iniciando agora.", flush=True)

    print("=" * 64, flush=True)

    voice_thread = threading.Thread(
        target=start_voice,
        args=(voice_runtime,),
        name="duque-voice",
        daemon=True,
    )
    voice_thread.start()

    threading.Thread(
        target=open_interface,
        args=(4.0,),
        name="duque-interface",
        daemon=True,
    ).start()

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
