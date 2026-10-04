from __future__ import annotations

import os
import queue
import threading
import time
from typing import Any, Callable
from uuid import uuid4

from .forge import Forge, ForgeReport, ForgeStatus
from .updater import RESTART_EXIT_CODE, Updater


def request_restart(delay: float = 4.0) -> bool:
    """Pede ao supervisor para reiniciar o Duque; sem supervisor, não faz nada."""
    if os.getenv("DUQUE_SUPERVISED") != "1":
        return False
    timer = threading.Timer(delay, lambda: os._exit(RESTART_EXIT_CODE))
    timer.daemon = True
    timer.start()
    return True


class ForgeService:
    """Fila de trabalhos da Forja rodando em segundo plano (um por vez)."""

    def __init__(
        self,
        forge: Forge,
        updater: Updater | None = None,
        *,
        restart: Callable[[], bool] = request_restart,
        notify: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> None:
        self.forge = forge
        self.updater = updater
        self.restart = restart
        self.notify = notify
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._lock = threading.Lock()
        self._current: dict[str, Any] | None = None
        self._history: list[dict[str, Any]] = []
        self._thread: threading.Thread | None = None
        # Protege a decisão "existe worker?" contra o worker que está saindo.
        self._worker_lock = threading.Lock()
        forge.progress = self._on_progress

    def submit(self, goal: str) -> dict[str, Any]:
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("objetivo da Forja não pode ser vazio")
        job = {"id": uuid4().hex[:8], "goal": goal.strip(), "state": "queued", "queued_at": time.time()}
        with self._worker_lock:
            self._queue.put(job)
            self._ensure_worker()
        return dict(job, position=self._queue.qsize())

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "current": dict(self._current) if self._current else None,
                "queued": self._queue.qsize(),
                "history": [dict(item) for item in self._history[-10:]],
            }

    def run_job(self, job: dict[str, Any]) -> ForgeReport:
        with self._lock:
            self._current = dict(job, state="running", step="iniciando")
        self._emit("forja_iniciada", {"goal": job["goal"]})
        report = self.forge.run(job["goal"])
        entry = {"id": job["id"], "goal": job["goal"], "status": report.status.value, "summary": report.summary(), "pr_url": report.pr_url}

        if report.status == ForgeStatus.MERGED and self.updater is not None:
            update = self.updater.apply()
            entry["update"] = update.status
            entry["update_message"] = update.message
            if update.status == "updated":
                restarting = self.restart()
                entry["restarting"] = restarting
                if restarting:
                    # O reinício é adiado alguns segundos: dá tempo de marcar a observação.
                    self.updater.mark_pending_restart(update)
                else:
                    entry["update_message"] += " (reinicie o Duque para usar a nova versão)"

        with self._lock:
            self._history.append(entry)
            self._current = None
        self._emit("forja_concluida", entry)
        return report

    # internos ------------------------------------------------------------
    def _ensure_worker(self) -> None:
        """Chamado com ``_worker_lock``: o worker só sai com a fila vazia sob o mesmo lock."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._worker, name="duque-forja", daemon=True)
        self._thread.start()

    def _worker(self) -> None:
        while True:
            try:
                job = self._queue.get(timeout=5)
            except queue.Empty:
                with self._worker_lock:
                    if self._queue.empty():
                        self._thread = None
                        return
                continue
            try:
                self.run_job(job)
            except Exception as exc:
                with self._lock:
                    self._history.append({"id": job["id"], "goal": job["goal"], "status": "failed", "summary": f"{type(exc).__name__}: {exc}"})
                    self._current = None

    def _on_progress(self, _report: ForgeReport, text: str) -> None:
        with self._lock:
            if self._current is not None:
                self._current["step"] = text
        self._emit("forja_progresso", {"step": text})

    def _emit(self, kind: str, data: dict[str, Any]) -> None:
        if self.notify:
            try:
                self.notify(kind, data)
            except Exception:
                pass
