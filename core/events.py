from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from threading import RLock
from time import time
from typing import Any, Callable


class EventType(str, Enum):
    RESPONSE_STARTED = "response_started"
    RESPONSE_FINISHED = "response_finished"
    TASK_STARTED = "task_started"
    TASK_FINISHED = "task_finished"
    TASK_FAILED = "task_failed"
    GOODBYE_DETECTED = "goodbye_detected"
    DUQUE_WAKE = "duque_wake"
    DUQUE_SLEEP = "duque_sleep"
    STATE_CHANGED = "state_changed"
    MEMORY_UPDATED = "memory_updated"
    OBSERVATION_STARTED = "observation_started"
    OBSERVATION_FINISHED = "observation_finished"
    VERIFICATION_STARTED = "verification_started"
    VERIFICATION_FINISHED = "verification_finished"
    ERROR = "error"


@dataclass(slots=True)
class Event:
    type: EventType
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time)


Subscriber = Callable[[Event], Any]

LOGGER = logging.getLogger(__name__)


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[EventType, list[Subscriber]] = {}
        self._wildcard: list[Subscriber] = []
        self._lock = RLock()

    def subscribe(self, event_type: EventType | None, callback: Subscriber) -> Callable[[], None]:
        with self._lock:
            target = self._wildcard if event_type is None else self._subscribers.setdefault(event_type, [])
            target.append(callback)

        def unsubscribe() -> None:
            with self._lock:
                if callback in target:
                    target.remove(callback)

        return unsubscribe

    def emit(self, event: Event) -> list[Any]:
        with self._lock:
            callbacks = [*self._subscribers.get(event.type, []), *self._wildcard]
        results: list[Any] = []
        # Um assinante com defeito (ex.: a atualização do HUD) nunca pode derrubar
        # quem emitiu o evento: antes uma falha de exibição interrompia a tarefa no
        # meio, deixava-a em "running" e a autocorreção repetia a mesma ação.
        for callback in callbacks:
            try:
                results.append(callback(event))
            except Exception:
                LOGGER.exception("Assinante falhou ao tratar %s", event.type.value)
        return results
