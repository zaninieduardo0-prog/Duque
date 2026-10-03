"""Ajustes específicos do Windows para o Duque rodar em segundo plano."""

from __future__ import annotations

import subprocess
import sys
from typing import Any

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def hide_console_windows(popen_cls: Any = subprocess.Popen, platform: str = sys.platform) -> bool:
    """Faz todo subprocesso iniciado pelo Duque rodar sem janela de console.

    O Duque roda com pythonw (sem console). Cada comando que ele dispara
    (tasklist do Spotify, git da Forja, abrir apps via cmd) criaria uma janela
    preta que pisca na tela. Quem passar creationflags explicitamente mantém
    o próprio valor.
    """
    if not platform.startswith("win"):
        return False
    if getattr(popen_cls, "_duque_no_window", False):
        return True
    original = popen_cls.__init__

    def __init__(self: Any, *args: Any, **kwargs: Any) -> None:
        if not kwargs.get("creationflags"):
            kwargs["creationflags"] = CREATE_NO_WINDOW
        original(self, *args, **kwargs)

    popen_cls.__init__ = __init__
    popen_cls._duque_no_window = True
    return True


def console_python(executable: str | None = None) -> str:
    """python.exe (de console) para rodar subprocessos, mesmo quando o TELEX roda pelo pythonw.

    Com o pythonw (sem console), cada git/cmd chamado pelos testes da Forja ganhava
    uma janela preta própria que piscava. Com python.exe + CREATE_NO_WINDOW, o
    console fica oculto e é herdado por tudo que ele chamar.
    """
    from pathlib import Path

    path = Path(executable or sys.executable)
    if path.name.casefold() == "pythonw.exe":
        candidate = path.with_name("python.exe")
        if candidate.exists():
            return str(candidate)
    return str(path)
