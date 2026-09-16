from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .events import Event, EventBus, EventType
from .state import DuqueState, StateManager, StateSnapshot


@dataclass(slots=True)
class EngineConfig:
    name: str = "Duque"
    version: str = "0.1.0"


class DuqueEngine:
    """Núcleo agnóstico de dispositivo; voz, HUD e apps são clientes dele."""

    def __init__(self, config: EngineConfig | None = None) -> None:
        self.config = config or EngineConfig()
        self.events = EventBus()
        self.state = StateManager()
        self.running = False

    def start(self) -> None:
        self.running = True
        self.state.transition(DuqueState.STANDBY, force=True, activity="Sistema pronto")
        self.events.emit(Event(EventType.DUQUE_WAKE))

    def sleep(self) -> None:
        self.state.transition(DuqueState.SLEEPING, force=True, activity="Duque em repouso")
        self.running = False
        self.events.emit(Event(EventType.DUQUE_SLEEP))

    def wake(self) -> None:
        self.running = True
        self.state.transition(DuqueState.STANDBY, force=True, activity="Sistema pronto")
        self.events.emit(Event(EventType.DUQUE_WAKE))

    def transition(self, state: DuqueState, **kwargs: Any) -> StateSnapshot:
        return self.state.transition(state, **kwargs)

    def emit(self, event_type: EventType, **data: Any) -> list[Any]:
        return self.events.emit(Event(event_type, data))
