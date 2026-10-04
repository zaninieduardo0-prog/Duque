from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ._proc import CONSOLE_ENCODING, IS_WINDOWS, NO_WINDOW, kill_tree, run_quiet
from .workspace import encode_text

# Variáveis cujo nome indica credencial nunca são devolvidas ao agente.
SENSITIVE_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "PASS", "PWD", "AUTH", "CREDENTIAL", "COOKIE", "SESSION", "PRIVATE")


def _is_sensitive(name: str) -> bool:
    upper = name.upper()
    if upper in {"PWD", "OLDPWD"}:  # diretório atual em shells POSIX
        return False
    return any(marker in upper for marker in SENSITIVE_MARKERS)


def _decode(data: bytes | str | None) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    return data.decode(CONSOLE_ENCODING or "utf-8", errors="replace")


class SystemTools:
    """Acesso amplo ao Windows e ao sistema local.

    A autorização de alto impacto é aplicada pelo Executor/SecurityPolicy.
    As funções retornam apenas dados JSON-serializáveis.
    """

    def system_info(self) -> dict[str, Any]:
        return {
            "platform": platform.platform(),
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python": platform.python_version(),
            "cwd": str(Path.cwd()),
            "user": os.getenv("USERNAME") or os.getenv("USER") or "",
            "computer": os.getenv("COMPUTERNAME") or platform.node(),
        }

    def environment(self, name: str | None = None) -> dict[str, Any]:
        # Não despejar chaves, tokens ou credenciais do ambiente no contexto do
        # agente, nem quando a variável é pedida pelo nome.
        if name:
            if _is_sensitive(name):
                return {"name": name, "value": None, "redacted": True, "exists": name in os.environ}
            return {"name": name, "value": os.getenv(name)}
        variables = {
            key: value
            for key, value in os.environ.items()
            if not _is_sensitive(key)
        }
        return {"variables": variables, "redacted": True}

    def list_directory(self, path: str = ".") -> dict[str, Any]:
        target = Path(path).expanduser().resolve()
        if not target.is_dir():
            raise NotADirectoryError(str(target))
        entries = []
        for item in sorted(target.iterdir(), key=lambda value: (not value.is_dir(), value.name.casefold())):
            entries.append({
                "name": item.name,
                "path": str(item),
                "type": "directory" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else None,
            })
        return {"path": str(target), "entries": entries, "count": len(entries)}

    def read_any_file(self, path: str, max_bytes: int = 2_000_000) -> dict[str, Any]:
        target = Path(path).expanduser().resolve()
        if not target.is_file():
            raise FileNotFoundError(str(target))
        limit = max(1, min(int(max_bytes), 10_000_000))
        with target.open("rb") as handle:
            data = handle.read(limit + 1)
        truncated = len(data) > limit
        data = data[:limit]
        try:
            content = data.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            content = data.decode("utf-8", errors="replace")
            encoding = "utf-8-replaced"
        return {
            "path": str(target),
            "content": content,
            "encoding": encoding,
            "bytes": len(data),
            "truncated": truncated,
        }

    def write_any_file(self, path: str, content: str) -> dict[str, Any]:
        target = Path(path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        existed = target.exists()
        new = encode_text(content)
        # Compara bytes: um arquivo existente em outra codificação não pode quebrar a escrita.
        old = target.read_bytes() if existed and target.is_file() else None
        target.write_bytes(new)
        return {
            "path": str(target),
            "created": not existed,
            "changed": old != new,
            "bytes": len(new),
        }

    def delete_any_file(self, path: str) -> dict[str, Any]:
        target = Path(path).expanduser().resolve()
        if not target.exists():
            raise FileNotFoundError(str(target))
        if target.is_dir():
            shutil.rmtree(target)
            return {"path": str(target), "deleted": True, "type": "directory"}
        target.unlink()
        return {"path": str(target), "deleted": True, "type": "file"}

    def copy_path(self, source: str, destination: str) -> dict[str, Any]:
        src = Path(source).expanduser().resolve()
        dst = Path(destination).expanduser().resolve()
        if not src.exists():
            raise FileNotFoundError(str(src))
        if src.is_dir() and (dst == src or dst.is_relative_to(src)):
            raise ValueError("O destino não pode ficar dentro da pasta de origem")
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
        return {"source": str(src), "destination": str(dst), "copied": True}

    def move_path(self, source: str, destination: str) -> dict[str, Any]:
        src = Path(source).expanduser().resolve()
        dst = Path(destination).expanduser().resolve()
        if not src.exists():
            raise FileNotFoundError(str(src))
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return {"source": str(src), "destination": str(dst), "moved": True}

    def run_command(self, command: str, timeout: int = 120) -> dict[str, Any]:
        command = command.strip()
        if not command:
            raise ValueError("command não pode ser vazio")
        limit = max(1, min(int(timeout), 600))
        cwd = str(Path.cwd())
        if IS_WINDOWS:
            # String única: com lista, o subprocess cita o comando de novo e o
            # /s do cmd.exe passa a remover as aspas erradas.
            args: str | list[str] = f'cmd.exe /d /s /c "{command}"'
        else:
            args = ["/bin/sh", "-lc", command]

        if command.casefold().startswith("start "):
            # Programas abertos com start ficam rodando: não espera nem captura saída.
            subprocess.Popen(
                args,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                creationflags=NO_WINDOW,
                start_new_session=not IS_WINDOWS,
            )
            return {"command": command, "detached": True, "return_code": None, "stdout": "", "stderr": "", "success": True}

        process = subprocess.Popen(
            args,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            creationflags=NO_WINDOW,
            start_new_session=not IS_WINDOWS,
        )
        try:
            stdout, stderr = process.communicate(timeout=limit)
        except subprocess.TimeoutExpired:
            kill_tree(process.pid)
            try:
                stdout, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                # Um neto pode manter os pipes abertos; não travar o agente por isso.
                stdout, stderr = b"", b""
            return {
                "command": command,
                "return_code": None,
                "stdout": _decode(stdout),
                "stderr": _decode(stderr),
                "timed_out": True,
                "success": False,
                "error": f"Comando excedeu {limit}s e foi encerrado",
            }
        return {
            "command": command,
            "return_code": process.returncode,
            "stdout": _decode(stdout),
            "stderr": _decode(stderr),
            "success": process.returncode == 0,
        }

    def list_processes(self) -> dict[str, Any]:
        if platform.system() == "Windows":
            completed = run_quiet(["tasklist", "/FO", "CSV", "/NH"], timeout=30, encoding=CONSOLE_ENCODING)
            rows = []
            for line in completed.stdout.splitlines():
                parts = [part.strip('"') for part in line.split('","')]
                if len(parts) >= 5:
                    rows.append({
                        "name": parts[0],
                        "pid": parts[1],
                        "session": parts[2],
                        "session_number": parts[3],
                        "memory": parts[4],
                    })
            return {"processes": rows, "count": len(rows)}
        completed = run_quiet(["ps", "-eo", "pid=,comm=,args="], timeout=30)
        rows = []
        for line in completed.stdout.splitlines():
            parts = line.strip().split(None, 2)
            if len(parts) >= 2:
                rows.append({"pid": parts[0], "name": parts[1], "command": parts[2] if len(parts) > 2 else ""})
        return {"processes": rows, "count": len(rows)}

    def kill_process(self, pid: int, force: bool = False) -> dict[str, Any]:
        pid = int(pid)
        if pid <= 0:
            raise ValueError("pid inválido")
        if pid in {os.getpid(), os.getppid()}:
            raise PermissionError("Não posso encerrar o próprio processo do Duque")
        if platform.system() == "Windows":
            args = ["taskkill", "/PID", str(pid)]
            if force:
                args.append("/F")
        else:
            args = ["kill", "-9" if force else "-15", str(pid)]
        completed = run_quiet(args, timeout=30, encoding=CONSOLE_ENCODING)
        return {
            "pid": pid,
            "force": force,
            "return_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "success": completed.returncode == 0,
        }

    def register(self, executor: Any) -> None:
        executor.register("system_info", self.system_info)
        executor.register("environment", self.environment)
        executor.register("list_directory", self.list_directory)
        executor.register("read_any_file", self.read_any_file)
        executor.register("write_any_file", self.write_any_file)
        executor.register("delete_any_file", self.delete_any_file)
        executor.register("copy_path", self.copy_path)
        executor.register("move_path", self.move_path)
        executor.register("run_command", self.run_command)
        executor.register("list_processes", self.list_processes)
        executor.register("kill_process", self.kill_process)
