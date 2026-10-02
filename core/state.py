from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from threading import RLock
from time import time
from typing import Callable


class DuqueState(str, Enum):
    STANDBY = "standby"
    LISTENING = "ouvindo"
    PROCESSING = "processando"
    EXECUTING = "executando"
    SPEAKING = "falando"
    SLEEPING = "dormindo"
    ERROR = "erro"


@dataclass(slots=True, frozen=True)
class StateSnapshot:
    state: DuqueState
    task: str = ""
    activity: str = ""
    coherence: int = 100
    updated_at: float = field(default_factory=time)


class InvalidTransition(ValueError):
    pass


class StateManager:
    _TRANSITIONS: dict[DuqueState, set[DuqueState]] = {
        DuqueState.STANDBY: {DuqueState.LISTENING, DuqueState.PROCESSING, DuqueState.SLEEPING, DuqueState.ERROR},
        DuqueState.LISTENING: {DuqueState.PROCESSING, DuqueState.STANDBY, DuqueState.SLEEPING, DuqueState.ERROR},
        DuqueState.PROCESSING: {DuqueState.EXECUTING, DuqueState.SPEAKING, DuqueState.STANDBY, DuqueState.SLEEPING, DuqueState.ERROR},
        DuqueState.EXECUTING: {DuqueState.PROCESSING, DuqueState.SPEAKING, DuqueState.STANDBY, DuqueState.ERROR},
        DuqueState.SPEAKING: {DuqueState.LISTENING, DuqueState.PROCESSING, DuqueState.STANDBY, DuqueState.SLEEPING, DuqueState.ERROR},
        DuqueState.SLEEPING: {DuqueState.STANDBY, DuqueState.LISTENING, DuqueState.ERROR},
        DuqueState.ERROR: {DuqueState.STANDBY, DuqueState.PROCESSING, DuqueState.LISTENING, DuqueState.SLEEPING},
    }

    def __init__(self, initial: DuqueState = DuqueState.STANDBY) -> None:
        self._snapshot = StateSnapshot(state=initial)
        self._lock = RLock()
        self._listeners: list[Callable[[StateSnapshot], None]] = []

    def subscribe(self, listener: Callable[[StateSnapshot], None]) -> Callable[[], None]:
        with self._lock:
            self._listeners.append(listener)

        def unsubscribe() -> None:
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return unsubscribe

    def snapshot(self) -> StateSnapshot:
        with self._lock:
            return self._snapshot

    def can_transition(self, target: DuqueState) -> bool:
        with self._lock:
            return target == self._snapshot.state or target in self._TRANSITIONS[self._snapshot.state]

    def transition(self, target: DuqueState, *, task: str = "", activity: str = "", coherence: int = 100, force: bool = False) -> StateSnapshot:
        with self._lock:
            current = self._snapshot.state
            if not force and target != current and target not in self._TRANSITIONS[current]:
                raise InvalidTransition(f"Transição inválida: {current.value} -> {target.value}")
            self._snapshot = StateSnapshot(target, task, activity, max(0, min(100, coherence)))
            listeners = tuple(self._listeners)
            snapshot = self._snapshot
        for listener in listeners:
            try:
                listener(snapshot)
            except Exception:
                pass
        return snapshot
