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
        # Pausa de emergência: a Forja para entre as etapas e continua de onde parou.
        self.pause: Any | None = None
        forge.progress = self._on_progress

    def submit(self, goal: str) -> dict[str, Any]:
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("objetivo da Forja não pode ser vazio")
        job = {"id": uuid4().hex[:8], "goal": goal.strip(), "state": "queued", "queued_at": time.time()}
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
            self._current = dict(job, state="running", step="iniciando", started_at=time.time(), steps=0)
        self._emit("forja_iniciada", {"goal": job["goal"]})
        report = self.forge.run(job["goal"])
        entry = {"id": job["id"], "goal": job["goal"], "status": report.status.value, "summary": report.summary(), "pr_url": report.pr_url}

        if report.status == ForgeStatus.MERGED and self.updater is not None:
            update = self.updater.apply()
            entry["update"] = update.status
            entry["update_message"] = update.message
            if update.status == "updated":
                entry["restarting"] = self.restart()

        with self._lock:
            self._history.append(entry)
            self._current = None
        self._emit("forja_concluida", entry)
        return report

    # internos ------------------------------------------------------------
    def _ensure_worker(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._worker, name="duque-forja", daemon=True)
        self._thread.start()

    def _worker(self) -> None:
        while True:
            try:
                job = self._queue.get(timeout=5)
            except queue.Empty:
                return
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
                self._current.setdefault("steps", 0)
                self._current["steps"] += 1
            goal = self._current.get("goal", "") if self._current else ""
        self._emit("forja_progresso", {"step": text})
        if self.pause is not None:
            self.pause.checkpoint("forja", {"trabalho": f"Forja: {goal}"[:90], "etapa": text})

    def _emit(self, kind: str, data: dict[str, Any]) -> None:
        if self.notify:
            try:
                self.notify(kind, data)
            except Exception:
                pass
