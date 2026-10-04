from __future__ import annotations

import os
import platform
import subprocess
import webbrowser
from pathlib import Path

from ._proc import NO_WINDOW


class ComputerController:
    """Interface controlada para ações no computador do usuário."""

    def open_url(self, url: str) -> None:
        # Chrome com o perfil do Du (computer/chrome.py); senão, o navegador padrão.
        if os.getenv("DUQUE_BROWSER", "chrome").casefold() == "chrome":
            from .chrome import open_in_chrome

            try:
                if open_in_chrome(url):
                    return
            except Exception:
                pass
        webbrowser.open(url)

    def open_url_verified(self, url: str, expect: str, timeout: float = 12.0) -> bool:
        """Abre o link e confere pelo título da janela que o site apareceu.

        Se o site já estiver aberto numa janela do Chrome, só traz a janela para a
        frente (sem página duplicada). Abre UMA vez. Fora do Windows não há como conferir.
        """
        from .windows_focus import IS_WINDOWS, focus_site, wait_for_window

        if IS_WINDOWS and focus_site(expect):
            return True
        self.open_url(url)
        if not IS_WINDOWS:
            return True
        # Abrir de novo quando o título demora (ou é diferente do esperado) só
        # duplicava a página: open_url já caiu no navegador padrão se o Chrome falhou.
        return wait_for_window(expect, timeout)

    def open_chrome(self) -> bool:
        """Traz o Chrome que já está aberto; só abre uma janela nova se não houver nenhuma."""
        from .chrome import open_in_chrome
        from .windows_focus import IS_WINDOWS, chrome_window_open, focus_chrome

        if IS_WINDOWS and chrome_window_open() and focus_chrome():
            return True
        return open_in_chrome(None)

    def open_path(self, path: str | Path) -> None:
        target = str(Path(path).expanduser())
        if platform.system() == "Windows":
            os.startfile(target)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(
                ["xdg-open", target],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )

    def launch(self, command: str | list[str] | tuple[str, ...]) -> subprocess.Popen | None:
        """Executa um programa explicitamente solicitado (sem shell).

        ``cmd.exe /c start "" <alvo>`` (protocolos como spotify:, App Paths como
        chrome) vira ``os.startfile(<alvo>)``: mesmo efeito, sem o cmd.exe e sem
        a janela de console que piscava. Falhas sobem como exceção.
        """
        args: list[str] = list(command) if isinstance(command, (list, tuple)) else [command]
        if not args:
            raise ValueError("Comando vazio")
        target = shell_target(args)
        if target is not None:
            if platform.system() != "Windows":
                raise RuntimeError(f"Abrir '{target}' pelo shell exige Windows")
            os.startfile(target)  # type: ignore[attr-defined]  # noqa: S606
            return None
        try:
            return subprocess.Popen(
                args, shell=False,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=NO_WINDOW,
            )
        except OSError as exc:
            # WinError 740: o programa pede administrador (ex.: taskmgr); o shell mostra o UAC.
            if platform.system() == "Windows" and getattr(exc, "winerror", None) == 740 and len(args) == 1:
                os.startfile(args[0])  # type: ignore[attr-defined]  # noqa: S606
                return None
            raise


def shell_target(args: list[str]) -> str | None:
    """["cmd.exe", "/c", "start", "", "spotify:"] -> "spotify:" (senão None)."""
    if len(args) == 5 and args[0].casefold() in {"cmd", "cmd.exe"} and args[1].casefold() == "/c" \
            and args[2].casefold() == "start" and args[3] == "" and args[4]:
        return args[4]
    return None
