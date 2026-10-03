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

os.environ.setdefault("DUQUE_WORKSPACE_ROOT", str(ROOT))
os.environ.setdefault("DUQUE_AUTONOMOUS_AGENT", "1")
os.environ.setdefault("DUQUE_PITCH", "-2.0")
os.environ.setdefault("DUQUE_VOICE_SPEED", "0.96")
os.environ.setdefault("DUQUE_VOICE_PROCESSING", "0")

LOG_PATH = ROOT / "duque.log"
LOG_FILE = LOG_PATH.open("a", encoding="utf-8", buffering=1)
sys.stdout = LOG_FILE
sys.stderr = LOG_FILE


URL = "http://127.0.0.1:5000"


def server_online() -> bool:
    try:
        with urllib.request.urlopen(f"{URL}/status", timeout=0.7) as response:
            return response.status == 200
    except Exception:
        return False


def open_interface() -> None:
    time.sleep(2.0)
    try:
        from computer.chrome import open_in_chrome

        # Chrome no perfil do Du (sem a tela de escolher conta); senão, o navegador padrão.
        if not open_in_chrome(URL):
            webbrowser.open_new_tab(URL)
    except Exception as exc:
        print(f"[DUQUE] Não consegui abrir a interface automaticamente: {exc}", flush=True)


def start_voice(voice_runtime) -> None:
    try:
        voice_runtime.log("Duque integrado: iniciando wake word + conversa de voz.")
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
    # Se o servidor já está ativo, esta é uma segunda tentativa de inicialização.
    # Não importamos o servidor/agente novamente para evitar duplicar scheduler e estado.
    if server_online():
        print("[DUQUE] Instância já ativa; abrindo a interface.", flush=True)
        open_interface()
        return

    # Só carregamos o servidor/agente depois da checagem de instância única.
    # Assim uma segunda abertura não cria outro AgentLoop nem outro scheduler.
    from servidor import app
    import duque_wake_v3 as voice_runtime

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
