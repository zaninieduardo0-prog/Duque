from __future__ import annotations

import os
import subprocess
from typing import Any

IS_WINDOWS = os.name == "nt"

# Evita que cada subprocesso abra (e pisque) uma janela de console no Windows.
NO_WINDOW: int = getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WINDOWS else 0

# Ferramentas de console do Windows (cmd, tasklist, taskkill) escrevem na
# página de código OEM; fora do Windows o padrão do locale é suficiente.
CONSOLE_ENCODING: str | None = "oem" if IS_WINDOWS else None


def run_quiet(
    args: list[str],
    *,
    timeout: float,
    cwd: str | None = None,
    encoding: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Executa sem shell, sem janela e sem quebrar com bytes inválidos na saída."""
    kwargs: dict[str, Any] = {}
    if env is not None:
        kwargs["env"] = env
    return subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding=encoding,
        errors="replace",
        stdin=subprocess.DEVNULL,
        timeout=timeout,
        shell=False,
        creationflags=NO_WINDOW,
        **kwargs,
    )


def kill_tree(pid: int) -> None:
    """Encerra um processo e todos os filhos (no Windows, via taskkill /T)."""
    try:
        if IS_WINDOWS:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(int(pid))],
                capture_output=True,
                stdin=subprocess.DEVNULL,
                timeout=10,
                shell=False,
                creationflags=NO_WINDOW,
            )
        else:
            import signal

            try:
                os.killpg(int(pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                os.kill(int(pid), signal.SIGKILL)
    except Exception:
        pass
