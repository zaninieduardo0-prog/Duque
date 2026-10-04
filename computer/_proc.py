"""Subprocessos do TELEX: sem janela de console, sem travar, sem quebrar na decodificação.

O TELEX roda pelo pythonw (sem console). Sem ``CREATE_NO_WINDOW`` cada
``tasklist``/``taskkill``/``git`` abriria uma janela preta que pisca. Ferramentas
de console do Windows escrevem na página de código OEM (cp850 no Brasil): ler
com o padrão ANSI estragava acentos ("Legião" → "Legi‡o").
"""

from __future__ import annotations

import os
import subprocess
IS_WINDOWS = os.name == "nt"

NO_WINDOW: int = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if IS_WINDOWS else 0

# "oem" só existe no Windows; fora dele o padrão do locale (UTF-8) serve.
CONSOLE_ENCODING: str = "oem" if IS_WINDOWS else "utf-8"


def decode(data: bytes | str | None, encoding: str = CONSOLE_ENCODING) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    try:
        return data.decode(encoding, errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


def kill_tree(pid: int) -> None:
    """Encerra um processo e todos os filhos (no Windows, ``taskkill /T /F``)."""
    try:
        if IS_WINDOWS:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(int(pid))],
                capture_output=True, stdin=subprocess.DEVNULL, timeout=10, shell=False, creationflags=NO_WINDOW,
            )
            return
        import signal

        # getattr: killpg/SIGKILL não existem no Windows (o pyright do CI checa lá).
        sigkill = getattr(signal, "SIGKILL", signal.SIGTERM)
        killpg = getattr(os, "killpg", None)
        try:
            if killpg is None:
                raise OSError("killpg indisponível")
            killpg(int(pid), sigkill)
        except (ProcessLookupError, PermissionError, OSError):
            os.kill(int(pid), sigkill)
    except Exception:
        pass


def run_quiet(
    args: list[str] | str,
    *,
    timeout: float,
    cwd: str | None = None,
    encoding: str = CONSOLE_ENCODING,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Roda sem shell e sem janela; no tempo esgotado mata a ÁRVORE e levanta ``TimeoutExpired``.

    ``subprocess.run`` só mata o filho direto e depois espera os pipes sem
    limite: um neto (ex.: um app gráfico aberto pelo comando) travava o TELEX.
    """
    process: subprocess.Popen[bytes] = subprocess.Popen(
        args,
        cwd=cwd,
        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        creationflags=NO_WINDOW,
        start_new_session=not IS_WINDOWS,
        env=env,
    )
    data = input_text.encode(encoding if encoding != "oem" else "utf-8", errors="replace") if input_text is not None else None
    try:
        stdout, stderr = process.communicate(data, timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_tree(process.pid)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:  # um neto segurando os pipes: não travar por isso
            stdout, stderr = b"", b""
        raise subprocess.TimeoutExpired(args, timeout, output=decode(stdout, encoding), stderr=decode(stderr, encoding)) from None
    return subprocess.CompletedProcess(args, process.returncode, decode(stdout, encoding), decode(stderr, encoding))
