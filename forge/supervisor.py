from __future__ import annotations

import os
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Protocol

from .git import Git, GitError
from .updater import RESTART_EXIT_CODE, read_state, write_state


class Process(Protocol):
    def poll(self) -> int | None: ...

    def wait(self) -> int: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


def http_healthy(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


class Supervisor:
    """Mantém o Duque rodando, reinicia após atualizações e faz rollback.

    - código de saída 75: o Duque pediu reinício (nova versão aplicada);
    - após uma atualização, a nova versão fica em observação: se não
      responder em /status dentro do prazo, volta para o commit anterior;
    - quedas repetidas em pouco tempo encerram o supervisor em vez de
      ficar reiniciando para sempre.
    """

    def __init__(
        self,
        root: str | Path,
        command: list[str],
        *,
        health_url: str = "http://127.0.0.1:5000/status",
        probation_seconds: float = 90,
        max_crashes: int = 5,
        crash_window: float = 600,
        spawn: Callable[[list[str], dict[str, str], Path], Process] | None = None,
        health: Callable[[], bool] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        log: Callable[[str], Any] = print,
    ) -> None:
        self.root = Path(root)
        self.command = command
        self.state_path = self.root / "duque_data" / "update_state.json"
        self.probation_seconds = probation_seconds
        self.max_crashes = max_crashes
        self.crash_window = crash_window
        self.spawn = spawn or self._spawn
        self.health = health or (lambda: http_healthy(health_url))
        self.sleep = sleep
        self.clock = clock
        self.log = log
        self.crashes: list[float] = []

    @staticmethod
    def _spawn(command: list[str], env: dict[str, str], cwd: Path) -> Process:
        return subprocess.Popen(command, cwd=str(cwd), env=env)

    def run(self) -> int:
        while True:
            env = dict(os.environ, DUQUE_SUPERVISED="1")
            process = self.spawn(self.command, env, self.root)
            state = read_state(self.state_path)

            if state.get("status") == "pending_restart":
                if self._wait_healthy(process):
                    write_state(self.state_path, status="ok", last_good=state.get("current"))
                    self.log(f"[SUPERVISOR] nova versão {str(state.get('current'))[:10]} saudável")
                else:
                    self._stop(process)
                    self._rollback(state)
                    continue

            code = process.wait()
            if code == RESTART_EXIT_CODE:
                self.log("[SUPERVISOR] reinício solicitado pelo Duque")
                continue
            if code == 0:
                self.log("[SUPERVISOR] Duque encerrado normalmente")
                return 0

            now = self.clock()
            self.crashes = [moment for moment in self.crashes if now - moment < self.crash_window] + [now]
            self.log(f"[SUPERVISOR] Duque caiu com código {code} ({len(self.crashes)}x)")
            if len(self.crashes) >= self.max_crashes:
                self.log("[SUPERVISOR] quedas demais em pouco tempo; parando")
                return code
            self.sleep(min(30, 2 ** len(self.crashes)))

    def _wait_healthy(self, process: Process) -> bool:
        deadline = self.clock() + self.probation_seconds
        while self.clock() < deadline:
            if process.poll() is not None:
                return False
            if self.health():
                return True
            self.sleep(2)
        return False

    def _stop(self, process: Process) -> None:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait()
            except Exception:
                process.kill()

    def _rollback(self, state: dict[str, Any]) -> None:
        previous = state.get("previous")
        git = Git(self.root)
        try:
            if not previous or git.head() != state.get("current"):
                write_state(self.state_path, status="rollback_skipped")
                self.log("[SUPERVISOR] não foi possível identificar a versão anterior; mantendo a atual")
                return
            git.run("reset", "--hard", str(previous))
            write_state(self.state_path, status="rolled_back", current=previous, failed=state.get("current"))
            self.log(f"[SUPERVISOR] nova versão não subiu; voltei para {str(previous)[:10]}")
        except GitError as exc:
            write_state(self.state_path, status="rollback_failed", error=str(exc))
            self.log(f"[SUPERVISOR] rollback falhou: {exc}")
