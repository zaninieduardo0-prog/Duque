from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ._proc import IS_WINDOWS, NO_WINDOW, decode, run_quiet
from .workspace import guard_project_source

# Variáveis cujo nome indica credencial nunca são devolvidas ao agente.
SENSITIVE_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "PASS", "AUTH", "CREDENTIAL", "COOKIE", "SESSION", "PRIVATE", "CERT")


def is_sensitive_variable(name: str) -> bool:
    upper = name.upper()
    return any(marker in upper for marker in SENSITIVE_MARKERS)


def windows_command_line(command: str) -> str:
    """Linha para o cmd.exe. Passada como string única: com lista, o subprocess
    citava o comando de novo (aspas viravam \\") e o /s do cmd removia as aspas erradas."""
    return f'cmd.exe /d /s /c "{command}"'


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
        # Chaves, tokens e senhas nunca vão para o contexto do agente (nem pedidas pelo nome).
        if name:
            if is_sensitive_variable(name):
                return {"name": name, "value": None, "redacted": True, "exists": name in os.environ}
            return {"name": name, "value": os.getenv(name)}
        variables = {key: value for key, value in os.environ.items() if not is_sensitive_variable(key)}
        return {"variables": variables, "redacted": True}

    def list_directory(self, path: str = ".") -> dict[str, Any]:
        target = Path(path).expanduser().resolve()
        if not target.is_dir():
            raise NotADirectoryError(str(target))
        entries = []
        for item in sorted(target.iterdir(), key=lambda value: (not value.is_dir(), value.name.casefold())):
            try:
                is_dir = item.is_dir()
                size = item.stat().st_size if item.is_file() else None
            except OSError:  # arquivo sem permissão/link quebrado: não derruba a listagem inteira
                is_dir, size = False, None
            entries.append({"name": item.name, "path": str(item), "type": "directory" if is_dir else "file", "size": size})
            if len(entries) >= 2000:
                break
        return {"path": str(target), "entries": entries, "count": len(entries), "truncated": len(entries) >= 2000}

    def read_any_file(self, path: str, max_bytes: int = 2_000_000) -> dict[str, Any]:
        target = Path(path).expanduser().resolve()
        if not target.is_file():
            raise FileNotFoundError(str(target))
        limit = max(1, min(int(max_bytes), 10_000_000))
        with target.open("rb") as handle:  # nunca carrega um arquivo enorme inteiro
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
        guard_project_source(target, "alterar")
        if target.is_dir():
            raise IsADirectoryError(str(target))
        target.parent.mkdir(parents=True, exist_ok=True)
        existed = target.exists()
        new = content.encode("utf-8")
        # Compara bytes: um arquivo existente em outra codificação não pode quebrar a escrita.
        old = target.read_bytes() if existed else None
        target.write_bytes(new)
        return {"path": str(target), "created": not existed, "changed": old != new, "bytes": len(new)}

    def delete_any_file(self, path: str) -> dict[str, Any]:
        target = Path(path).expanduser().resolve()
        if not target.exists():
            raise FileNotFoundError(str(target))
        guard_project_source(target, "apagar")
        if target == Path(target.anchor) or target == Path.home().resolve():
            raise PermissionError(f"Não apago a raiz do disco nem a pasta pessoal: {target}")
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
        guard_project_source(dst, "alterar")
        if src.is_dir() and (dst == src or dst.is_relative_to(src)):
            raise ValueError("O destino não pode ficar dentro da pasta de origem (copiaria sem fim)")
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
        guard_project_source(src, "mover")
        guard_project_source(dst, "alterar")
        if src.is_dir() and (dst == src or dst.is_relative_to(src)):
            raise ValueError("O destino não pode ficar dentro da pasta de origem")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return {"source": str(src), "destination": str(dst), "moved": True}

    def run_command(self, command: str, timeout: int = 120) -> dict[str, Any]:
        command = command.strip()
        if not command:
            raise ValueError("command não pode ser vazio")
        limit = max(1, min(int(timeout), 600))
        cwd = str(Path.cwd())
        args: str | list[str] = windows_command_line(command) if IS_WINDOWS else ["/bin/sh", "-lc", command]
        if command.casefold().startswith("start "):
            # Programa aberto com start continua rodando: não espera nem captura (senão travava).
            subprocess.Popen(
                args, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                shell=False, creationflags=NO_WINDOW, start_new_session=not IS_WINDOWS,
            )
            return {"command": command, "detached": True, "return_code": None, "stdout": "", "stderr": "", "success": True}
        try:
            completed = run_quiet(args, cwd=cwd, timeout=limit)  # type: ignore[arg-type]
        except subprocess.TimeoutExpired as exc:
            return {
                "command": command, "return_code": None, "stdout": decode(exc.output), "stderr": decode(exc.stderr),
                "timed_out": True, "success": False, "error": f"Comando excedeu {limit}s e foi encerrado (com os processos filhos).",
            }
        return {
            "command": command,
            "return_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "success": completed.returncode == 0,
        }

    def list_processes(self) -> dict[str, Any]:
        if platform.system() == "Windows":
            completed = run_quiet(["tasklist", "/FO", "CSV", "/NH"], timeout=30)
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
        completed = run_quiet(["ps", "-eo", "pid=,comm=,args="], timeout=30, encoding="utf-8")
        rows = []
        for line in completed.stdout.splitlines():
            parts = line.strip().split(None, 2)
            if len(parts) >= 2:
                rows.append({"pid": parts[0], "name": parts[1], "command": parts[2] if len(parts) > 2 else ""})
        return {"processes": rows, "count": len(rows)}

    def kill_process(self, pid: int, force: bool = False) -> dict[str, Any]:
        pid = int(pid)
        if pid <= 4:  # 0 = ocioso, 4 = System no Windows; 1 = init
            raise ValueError("pid inválido")
        if pid in {os.getpid(), os.getppid()}:
            raise PermissionError("Não encerro o próprio TELEX por aqui; use 'Telex, desligar'.")
        if platform.system() == "Windows":
            args = ["taskkill", "/PID", str(pid)]
            if force:
                args.append("/F")
        else:
            args = ["kill", "-9" if force else "-15", str(pid)]
        completed = run_quiet(args, timeout=30)
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
