from __future__ import annotations

from .engine import DuqueEngine
from .events import EventType
from .state import DuqueState


class LifecycleManager:
    """Coordena o ciclo de vida sem misturar desligamento com a camada de voz."""

    def __init__(self, engine: DuqueEngine) -> None:
        self.engine = engine

    @property
    def active(self) -> bool:
        return self.engine.running

    def boot(self) -> None:
        self.engine.start()

    def sleep(self) -> None:
        if not self.engine.running and self.engine.state.snapshot().state == DuqueState.SLEEPING:
            return
        self.engine.emit(EventType.GOODBYE_DETECTED)
        self.engine.sleep()

    def wake(self) -> None:
        if self.engine.running:
            return
        self.engine.wake()

    def shutdown(self) -> None:
        """Entra em repouso uma única vez; o Engine é a fonte do evento de sleep."""
        if not self.engine.running and self.engine.state.snapshot().state == DuqueState.SLEEPING:
            return
        self.engine.sleep()
