from __future__ import annotations

import os
import platform
import subprocess
import webbrowser
from dataclasses import dataclass
from pathlib import Path

from ._proc import NO_WINDOW


@dataclass(slots=True, frozen=True)
class ShellTarget:
    """Alvo aberto pelo shell do Windows (protocolo, App Paths), sem console."""

    target: str


class ComputerController:
    """Interface controlada para ações no computador do usuário."""

    def open_url(self, url: str) -> None:
        webbrowser.open(url)

    def open_path(self, path: str | Path) -> None:
        target = str(Path(path).expanduser())
        if platform.system() == "Windows":
            os.startfile(target)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(
                ["xdg-open", target],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def launch(self, command: ShellTarget | list[str] | tuple[str, ...]) -> subprocess.Popen | None:
        """Executa um programa explicitamente solicitado.

        A camada de segurança/autorizações deverá validar comandos antes de
        chegar aqui. Não usamos shell=True. Um ``ShellTarget`` é aberto via
        ``os.startfile`` (ShellExecute), evitando ``cmd.exe /c start`` e a
        janela de console que piscava; falhas são propagadas.
        """
        if isinstance(command, ShellTarget):
            if platform.system() != "Windows":
                raise RuntimeError(f"Abrir '{command.target}' pelo shell exige Windows")
            os.startfile(command.target)  # type: ignore[attr-defined]
            return None
        args = list(command)
        if not args:
            raise ValueError("Comando vazio")
        return subprocess.Popen(
            args,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=NO_WINDOW,
        )
