"""Ponto de entrada recomendado do Duque.

Roda o duque.py como processo filho, reinicia quando a Forja aplica uma
atualização e volta para a versão anterior se a nova não subir.
"""

from __future__ import annotations

import sys
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
        log_file.write(message + "\n")

    supervisor = Supervisor(ROOT, [sys.executable, str(ROOT / "duque.py")], log=log)
    return supervisor.run()


if __name__ == "__main__":
    sys.exit(main())
