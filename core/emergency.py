"""Pausa de emergência: para o TELEX inteiro e guarda onde cada trabalho parou.

Não é um "cancelar tudo". Cada trabalho longo (etapa de tarefa, Forja, agenda)
passa por ``checkpoint()`` antes de continuar; durante a pausa ele fica parado
ali, com o ponto anotado, e segue do mesmo lugar quando o Du retoma.

O estado fica gravado em ``duque_data/pausa.json``: se o TELEX reiniciar no
meio de uma pausa, ele volta pausado e sabe o que estava fazendo.
"""

from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any, Callable

DEFAULT_PATH = Path("duque_data") / "pausa.json"

Listener = Callable[[bool, dict[str, Any]], Any]


class EmergencyPause:
    def __init__(self, path: str | Path | None = DEFAULT_PATH, clock: Callable[[], float] = time.time) -> None:
        self.path = Path(path) if path else None
        self._clock = clock
        self._cond = threading.Condition()
        self._paused = False
        self._since: float | None = None
        self._reason = ""
        self._checkpoints: dict[str, dict[str, Any]] = {}
        self._interrupted: list[dict[str, Any]] = []
        self._listeners: list[Listener] = []
        self._load()

    # estado -------------------------------------------------------------------
    @property
    def paused(self) -> bool:
        with self._cond:
            return self._paused

    def status(self) -> dict[str, Any]:
        with self._cond:
            return self._status_locked()

    def on_change(self, listener: Listener) -> None:
        """Chamado com (pausado, status) a cada pausa/retomada (voz, HUD...)."""
        with self._cond:
            self._listeners.append(listener)

    # comandos -----------------------------------------------------------------
    def pause(self, reason: str = "pedido do Du") -> dict[str, Any]:
        with self._cond:
            if not self._paused:
                self._paused = True
                self._since = self._clock()
                self._reason = reason
                self._save()
            status = self._status_locked()
        self._notify(True, status)
        return status

    def resume(self) -> dict[str, Any]:
        """Libera tudo que estava parado e devolve onde cada coisa estava."""
        with self._cond:
            was = self._status_locked()
            self._paused = False
            self._since = None
            self._reason = ""
            self._interrupted = []
            self._save()
            self._cond.notify_all()
        self._notify(False, was)
        return was

    # usado pelos trabalhos longos --------------------------------------------
    def checkpoint(self, key: str, info: dict[str, Any] | None = None, *, timeout: float | None = None) -> bool:
        """Ponto seguro de um trabalho. Em pausa, anota onde parou e espera.

        Devolve True se precisou esperar. ``timeout`` existe para os testes; em
        uso normal o trabalho espera o tempo que for preciso.
        """
        with self._cond:
            if not self._paused:
                return False
            entry = dict(info or {})
            entry.setdefault("desde", self._clock())
            self._checkpoints[key] = entry
            self._save()
            deadline = None if timeout is None else time.monotonic() + timeout
            while self._paused:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    break
                self._cond.wait(remaining if remaining is not None else 1.0)
            self._checkpoints.pop(key, None)
            self._save()
            return True

    # internos -----------------------------------------------------------------
    def _status_locked(self) -> dict[str, Any]:
        return {
            "pausado": self._paused,
            "desde": self._since,
            "motivo": self._reason,
            "parado_em": [dict(item, chave=key) for key, item in self._checkpoints.items()],
            "interrompido": [dict(item) for item in self._interrupted],
        }

    def _notify(self, paused: bool, status: dict[str, Any]) -> None:
        with self._cond:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(paused, status)
            except Exception:
                pass

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "pausado": self._paused,
                "desde": self._since,
                "motivo": self._reason,
                "parado_em": list(self._checkpoints.values()) + self._interrupted,
            }
            # Grava e troca de uma vez: um desligamento no meio da escrita deixava
            # um pausa.json pela metade e a pausa se perdia no próximo início.
            temporary = self.path.with_name(self.path.name + ".tmp")
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.path)
        except OSError:
            pass

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict) or not data.get("pausado"):
            return
        # Reiniciou no meio de uma pausa: continua pausado. Os trabalhos que
        # estavam parados não existem mais neste processo; ficam registrados
        # para o TELEX contar ao Du o que foi interrompido.
        self._paused = True
        self._since = data.get("desde")
        self._reason = str(data.get("motivo") or "")
        self._interrupted = [dict(item, reiniciado=True) for item in data.get("parado_em") or [] if isinstance(item, dict)]


# frases ------------------------------------------------------------------------

def _plain(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", (text or "").casefold())
    plain = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", plain))


_PAUSE_RE = re.compile(
    r"\b(pausa de emergencia|parada de emergencia|pausa tudo|pausar tudo|para tudo|parar tudo|congela tudo)\b"
)
_RESUME_RE = re.compile(
    r"^(telex |duque )?(retomar|retoma|retome|continuar|continua|continue|pode continuar|volta|voltar)( telex| duque)?( tudo| de onde parou| o que estava fazendo)?$"
)


def is_pause_command(text: str) -> bool:
    return bool(_PAUSE_RE.search(_plain(text)))


def is_resume_command(text: str) -> bool:
    return bool(_RESUME_RE.match(_plain(text)))


def describe(status: dict[str, Any]) -> str:
    """Frase curta (para falar) com o que estava parado."""
    items = list(status.get("parado_em") or []) + list(status.get("interrompido") or [])
    if not items:
        return "Nada estava em andamento."
    parts = []
    for item in items[:3]:
        what = str(item.get("trabalho") or item.get("chave") or "trabalho")
        where = str(item.get("etapa") or "").strip()
        text = f"{what}, em {where}" if where else what
        if item.get("reiniciado"):
            text += " (interrompido por um reinício)"
        parts.append(text)
    extra = len(items) - len(parts)
    return "Estava parado: " + "; ".join(parts) + (f"; e mais {extra}." if extra > 0 else ".")


emergency = EmergencyPause()


_SHUTDOWN_RE = re.compile(
    r"^(?:telex )?(?:(?:pode )?(?:se )?(?:deslig(?:a|ar|ue)(?:-se)?|encerr(?:a|ar|e)|deslig(?:a|ar|ue) tudo)"
    r"(?: o telex| voce| o sistema| o assistente)?|(?:deslig(?:a|ar|ue)|encerr(?:a|ar|e)|fech(?:a|ar|e)) o telex)$"
)


def is_shutdown_command(text: str) -> bool:
    """ "Telex, desligar" / "desligue o TELEX" / "encerrar" (não "desligue o computador")."""
    return bool(_SHUTDOWN_RE.match(_plain(text)))


def shutdown_soon(delay: float = 2.5) -> None:
    """Encerra o TELEX (o supervisor entende o código 0 como "parar de vez")."""
    import os

    timer = threading.Timer(delay, lambda: os._exit(0))
    timer.daemon = True
    timer.start()
