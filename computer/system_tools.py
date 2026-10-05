from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any


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
        if name:
            return {"name": name, "value": os.getenv(name)}
        sensitive_markers = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASS", "AUTH", "CREDENTIAL")
        variables = {
            key: value
            for key, value in os.environ.items()
            if not any(marker in key.upper() for marker in sensitive_markers)
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
        data = target.read_bytes()
        truncated = len(data) > limit
        data = data[:limit]
        try:
            content = data.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            content = data.decode("utf-8", errors="replace")
            encoding = "utf-8-replaced"
        return {"path": str(target), "content": content, "encoding": encoding, "bytes": len(data), "truncated": truncated}

    def write_any_file(self, path: str, content: str) -> dict[str, Any]:
        target = Path(path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        existed = target.exists()
        old = target.read_text(encoding="utf-8") if existed and target.is_file() else None
        target.write_text(content, encoding="utf-8")
        return {"path": str(target), "created": not existed, "changed": old != content, "bytes": len(content.encode("utf-8"))}

    def write_desktop_file(self, filename: str, content: str) -> dict[str, Any]:
        """Cria um único arquivo diretamente na Área de Trabalho, sem aceitar caminhos."""
        name = str(filename).strip().strip(' \\"“”\'')
        if not name or name in {".", ".."} or Path(name).name != name or "/" in name or "\\" in name:
            raise ValueError("nome de arquivo inválido")
        desktop = Path.home() / "Desktop"
        target = (desktop / name).resolve()
        if target.parent != desktop.resolve():
            raise ValueError("caminho fora da Área de Trabalho")
        desktop.mkdir(parents=True, exist_ok=True)
        existed = target.exists()
        old = target.read_text(encoding="utf-8") if existed and target.is_file() else None
        target.write_text(str(content), encoding="utf-8")
        return {"path": str(target), "created": not existed, "changed": old != content, "bytes": len(str(content).encode("utf-8"))}

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
        args = ["cmd.exe", "/d", "/s", "/c", command] if platform.system() == "Windows" else ["/bin/sh", "-lc", command]
        completed = subprocess.run(args, cwd=str(Path.cwd()), capture_output=True, text=True, timeout=limit, shell=False)
        return {"command": command, "return_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr, "success": completed.returncode == 0}

    def list_processes(self) -> dict[str, Any]:
        if platform.system() == "Windows":
            completed = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=30, shell=False)
            rows = []
            for line in completed.stdout.splitlines():
                parts = [part.strip('"') for part in line.split('","')]
                if len(parts) >= 5:
                    rows.append({"name": parts[0], "pid": parts[1], "session": parts[2], "session_number": parts[3], "memory": parts[4]})
            return {"processes": rows, "count": len(rows)}
        completed = subprocess.run(["ps", "-eo", "pid=,comm=,args="], capture_output=True, text=True, timeout=30, shell=False)
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
        args = ["taskkill", "/PID", str(pid)] + (["/F"] if force else []) if platform.system() == "Windows" else ["kill", "-9" if force else "-15", str(pid)]
        completed = subprocess.run(args, capture_output=True, text=True, timeout=30, shell=False)
        return {"pid": pid, "force": force, "return_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr, "success": completed.returncode == 0}

    def register(self, executor: Any) -> None:
        executor.register("system_info", self.system_info)
        executor.register("environment", self.environment)
        executor.register("list_directory", self.list_directory)
        executor.register("read_any_file", self.read_any_file)
        executor.register("write_any_file", self.write_any_file)
        executor.register("write_desktop_file", self.write_desktop_file)
        executor.register("delete_any_file", self.delete_any_file)
        executor.register("copy_path", self.copy_path)
        executor.register("move_path", self.move_path)
        executor.register("run_command", self.run_command)
        executor.register("list_processes", self.list_processes)
        executor.register("kill_process", self.kill_process)
