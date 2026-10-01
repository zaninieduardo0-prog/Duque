from __future__ import annotations

import os
import platform
import subprocess
import webbrowser
from pathlib import Path


class ComputerController:
    """Interface controlada para ações no computador do usuário."""

    def open_url(self, url: str) -> None:
        webbrowser.open(url)

    def open_path(self, path: str | Path) -> None:
        target = str(Path(path).expanduser())
        if platform.system() == "Windows":
            os.startfile(target)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", target])

    def launch(self, command: str | list[str] | tuple[str, ...]) -> subprocess.Popen:
        """Executa um programa explicitamente solicitado.

        A camada de segurança/autorizações deverá validar comandos antes de
        chegar aqui. Não usamos shell=True por padrão.
        """
        args: list[str] = list(command) if isinstance(command, (list, tuple)) else [command]
        return subprocess.Popen(args, shell=False)
