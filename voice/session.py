from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock


@dataclass(slots=True)
class RealtimeSessionState:
    """Estado síncrono mínimo para impedir áudio atrasado entre sessões."""

    active: bool = False
    accepting_input: bool = False
    shutting_down: bool = False
    generation: int = 0
    pending_audio: int = 0
    current_item: str | None = None
    _lock: Lock = field(default_factory=Lock, repr=False)

    def start(self) -> int:
        with self._lock:
            self.generation += 1
            self.active = True
            self.accepting_input = True
            self.shutting_down = False
            self.pending_audio = 0
            self.current_item = None
            return self.generation

    def begin_shutdown(self) -> int:
        with self._lock:
            self.shutting_down = True
            self.accepting_input = False
            return self.generation

    def stop(self) -> None:
        with self._lock:
            self.active = False
            self.accepting_input = False
            self.shutting_down = False
            self.pending_audio = 0
            self.current_item = None

    def accepts_audio(self, generation: int) -> bool:
        with self._lock:
            return self.active and generation == self.generation and not self.shutting_down

    def accepts_playback(self, generation: int) -> bool:
        """Permite terminar áudio da sessão mesmo após pedido de encerramento."""
        with self._lock:
            return self.active and generation == self.generation

    def add_audio(
        self,
        generation: int,
        item_id: str | None = None,
        *,
        allow_shutdown: bool = False,
    ) -> bool:
        with self._lock:
            if not self.active or generation != self.generation:
                return False
            if self.shutting_down and not allow_shutdown:
                return False
            self.pending_audio += 1
            if item_id is not None:
                self.current_item = item_id
            return True

    def consume_audio(self, generation: int) -> bool:
        with self._lock:
            if generation != self.generation:
                return False
            if self.pending_audio > 0:
                self.pending_audio -= 1
            return True

    def playback_drained(self) -> bool:
        with self._lock:
            return self.pending_audio == 0


class PlaybackFence:
    """Barreira de sessão para callbacks de áudio tardios."""

    def __init__(self, state: RealtimeSessionState | None = None) -> None:
        self.state = state or RealtimeSessionState()

    def new_session(self) -> int:
        return self.state.start()

    def shutdown(self) -> int:
        return self.state.begin_shutdown()

    def can_enqueue(
        self,
        generation: int,
        item_id: str | None = None,
        *,
        allow_shutdown: bool = False,
    ) -> bool:
        return self.state.add_audio(
            generation,
            item_id,
            allow_shutdown=allow_shutdown,
        )

    def can_consume(self, generation: int) -> bool:
        return self.state.consume_audio(generation)

    def stale(self, generation: int, *, allow_shutdown: bool = False) -> bool:
        if allow_shutdown:
            return not self.state.accepts_playback(generation)
        return not self.state.accepts_audio(generation)

    def drained(self) -> bool:
        return self.state.playback_drained()

    def close(self) -> None:
        self.state.stop()
