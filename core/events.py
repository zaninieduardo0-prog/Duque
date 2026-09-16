from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import time
from typing import Any, Callable


class EventType(str, Enum):
    WAKEWORD_DETECTED = "wakeword_detected"
    VOICE_STARTED = "voice_started"
    VOICE_ENDED = "voice_ended"
    USER_SPEECH_DETECTED = "user_speech_detected"
    USER_INTERRUPTED = "user_interrupted"
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


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[EventType, list[Subscriber]] = {}
        self._wildcard: list[Subscriber] = []

    def subscribe(self, event_type: EventType | None, callback: Subscriber) -> Callable[[], None]:
        target = self._wildcard if event_type is None else self._subscribers.setdefault(event_type, [])
        target.append(callback)

        def unsubscribe() -> None:
            if callback in target:
                target.remove(callback)

        return unsubscribe

    def emit(self, event: Event) -> list[Any]:
        callbacks = [*self._subscribers.get(event.type, []), *self._wildcard]
        return [callback(event) for callback in callbacks]
