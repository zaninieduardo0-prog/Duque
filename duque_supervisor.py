"""Ponto de entrada recomendado do Duque.

Roda o duque.py como processo filho, reinicia quando a Forja aplica uma
atualização e volta para a versão anterior se a nova não subir.

Só um supervisor por vez (trava em duque_data/supervisor.lock): abrir o TELEX
de novo enquanto ele já roda (início com o Windows + clique no Duque.vbs) não
cria um segundo supervisor disputando o update_state.json e o rollback; a
segunda abertura só roda o duque.py uma vez, que mostra a interface da
instância que já está no ar.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from core.windows import hide_console_windows
from forge.supervisor import Supervisor

ROOT = Path(__file__).resolve().parent


def main() -> int:
    hide_console_windows()
    log_path = ROOT / "duque_data" / "supervisor.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("a", encoding="utf-8", buffering=1)

    def log(message: str) -> None:
        log_file.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")

    command = [sys.executable, str(ROOT / "duque.py")]
    from core.instance import InstanceLock

    lock = InstanceLock(ROOT / "duque_data" / "supervisor.lock")
    if not lock.acquire():
        log("[SUPERVISOR] já existe um supervisor rodando; só mostrando a interface.")
        try:
            return subprocess.call(command, cwd=str(ROOT))
        except OSError as exc:
            log(f"[SUPERVISOR] não consegui abrir o Duque: {exc}")
            return 1
    try:
        log("[SUPERVISOR] iniciado")
        return Supervisor(ROOT, command, log=log).run()
    except Exception as exc:  # roda sem janela (pythonw): o erro precisa ficar no log
        import traceback

        log(f"[SUPERVISOR] falha inesperada: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")
        return 1
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
