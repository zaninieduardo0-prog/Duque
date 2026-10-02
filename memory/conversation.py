from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from threading import RLock
from typing import Any

from .memory import Memory, MemoryLayer

ROLES = {"user", "assistant"}
PERSIST_KEY = "conversa:recente"


@dataclass(slots=True, frozen=True)
class Turn:
    id: int
    role: str      # user | assistant
    text: str
    channel: str   # texto | voz | aviso
    at: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ConversationStore:
    """Uma única conversa compartilhada entre texto, voz e avisos.

    É o que permite digitar uma mensagem, depois dizer "Hey Jarvis" e continuar
    exatamente do mesmo ponto (e vice-versa). Os turnos mais recentes são
    persistidos para sobreviver a reinícios.
    """

    def __init__(self, memory: Memory | None = None, *, limit: int = 200, persist: int = 60) -> None:
        self.memory = memory
        self.limit = limit
        self.persist = persist
        self._lock = RLock()
        self._turns: list[Turn] = []
        self._next_id = 1
        self._restore()

    def add(self, role: str, text: str, channel: str = "texto") -> Turn | None:
        value = (text or "").strip()
        if role not in ROLES or not value:
            return None
        with self._lock:
            last = self._turns[-1] if self._turns else None
            # A mesma fala pode chegar por dois caminhos (ex.: evento duplicado da voz).
            if last and last.role == role and last.text == value and time.time() - last.at < 5:
                return last
            turn = Turn(self._next_id, role, value, channel, time.time())
            self._next_id += 1
            self._turns.append(turn)
            if len(self._turns) > self.limit:
                self._turns = self._turns[-self.limit:]
            self._save()
            return turn

    def recent(self, count: int = 20) -> list[Turn]:
        with self._lock:
            return list(self._turns[-count:]) if count > 0 else []

    def since(self, turn_id: int) -> list[Turn]:
        with self._lock:
            return [turn for turn in self._turns if turn.id > turn_id]

    def last_id(self) -> int:
        with self._lock:
            return self._turns[-1].id if self._turns else 0

    def as_messages(self, count: int = 16) -> list[dict[str, str]]:
        """Histórico no formato de mensagens de modelo (sem a mensagem atual)."""
        return [{"role": turn.role, "content": turn.text} for turn in self.recent(count)]

    def transcript(self, count: int = 12, max_chars: int = 3000) -> str:
        """Resumo legível para dar contexto a uma nova sessão de voz."""
        lines = []
        for turn in self.recent(count):
            who = "Du" if turn.role == "user" else "Duque"
            lines.append(f"{who} ({turn.channel}): {turn.text}")
        text = "\n".join(lines)
        return text[-max_chars:]

    # persistência ----------------------------------------------------------
    def _save(self) -> None:
        if self.memory is None:
            return
        try:
            payload = [turn.to_dict() for turn in self._turns[-self.persist:]]
            self.memory.remember(MemoryLayer.CONVERSATION, PERSIST_KEY, payload)
        except Exception:
            pass

    def _restore(self) -> None:
        if self.memory is None:
            return
        try:
            data = self.memory.recall(MemoryLayer.CONVERSATION, PERSIST_KEY, [])
            if isinstance(data, str):
                data = json.loads(data)
            for item in data or []:
                turn = Turn(int(item["id"]), str(item["role"]), str(item["text"]), str(item.get("channel", "texto")), float(item["at"]))
                if turn.role in ROLES:
                    self._turns.append(turn)
            if self._turns:
                self._next_id = self._turns[-1].id + 1
        except Exception:
            self._turns = []
            self._next_id = 1
