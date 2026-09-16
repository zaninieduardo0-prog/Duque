"""Núcleo do Duque: estado, eventos e ciclo de vida."""

from .engine import DuqueEngine, EngineConfig
from .events import Event, EventBus, EventType
from .state import DuqueState, InvalidTransition, StateManager, StateSnapshot

__all__ = [
    "DuqueEngine",
    "EngineConfig",
    "Event",
    "EventBus",
    "EventType",
    "DuqueState",
    "InvalidTransition",
    "StateManager",
    "StateSnapshot",
]
