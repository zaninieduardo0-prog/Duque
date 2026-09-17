from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from threading import Lock
from typing import Any, Callable


class VoiceSessionState(str, Enum):
    STANDBY = "standby"
    STARTING = "starting"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    SHUTTING_DOWN = "shutting_down"
    STOPPED = "stopped"


@dataclass(slots=True)
class VoiceSessionSnapshot:
    generation: int
    state: VoiceSessionState
    shutdown_requested: bool
    microphone_enabled: bool


class VoiceSessionLifecycle:
    """Fonte única de verdade para o ciclo de vida de uma sessão de voz.

    A geração invalida callbacks atrasados de uma sessão anterior. O encerramento
    é idempotente e só libera a sessão depois que o playback sinaliza drenagem.
    """

    def __init__(self, *, on_state: Callable[[VoiceSessionSnapshot], Any] | None = None) -> None:
        self._lock = Lock()
        self._generation = 0
        self._state = VoiceSessionState.STANDBY
        self._shutdown_requested = False
        self._microphone_enabled = False
        self._on_state = on_state
        self._playback_drained: asyncio.Event | None = None

    def start(self) -> int:
        with self._lock:
            self._generation += 1
            self._state = VoiceSessionState.STARTING
            self._shutdown_requested = False
            self._microphone_enabled = False
            generation = self._generation
            self._playback_drained = asyncio.Event()
        self._publish()
        return generation

    def is_current(self, generation: int) -> bool:
        with self._lock:
            return generation == self._generation and self._state != VoiceSessionState.STOPPED

    def enable_microphone(self, generation: int) -> bool:
        with self._lock:
            if generation != self._generation or self._shutdown_requested:
                return False
            self._microphone_enabled = True
            self._state = VoiceSessionState.LISTENING
        self._publish()
        return True

    def disable_microphone(self, generation: int) -> bool:
        with self._lock:
            if generation != self._generation:
                return False
            self._microphone_enabled = False
        self._publish()
        return True

    def transition(self, generation: int, state: VoiceSessionState) -> bool:
        with self._lock:
            if generation != self._generation or self._shutdown_requested:
                return False
            self._state = state
        self._publish()
        return True

    def request_shutdown(self, generation: int) -> bool:
        with self._lock:
            if generation != self._generation:
                return False
            if self._shutdown_requested:
                return False
            self._shutdown_requested = True
            self._microphone_enabled = False
            self._state = VoiceSessionState.SHUTTING_DOWN
        self._publish()
        return True

    def accepts_microphone(self, generation: int) -> bool:
        with self._lock:
            return (
                generation == self._generation
                and self._microphone_enabled
                and not self._shutdown_requested
                and self._state not in {VoiceSessionState.STOPPED, VoiceSessionState.SHUTTING_DOWN}
            )

    def mark_playback_drained(self, generation: int) -> bool:
        with self._lock:
            if generation != self._generation:
                return False
            event = self._playback_drained
        if event is not None:
            event.set()
        return True

    async def wait_playback_drained(self, generation: int, timeout: float = 5.0) -> bool:
        with self._lock:
            if generation != self._generation:
                return False
            event = self._playback_drained
        if event is None:
            return False
        try:
            await asyncio.wait_for(event.wait(), timeout=max(0.0, timeout))
            return True
        except asyncio.TimeoutError:
            return False

    def stop(self, generation: int) -> bool:
        with self._lock:
            if generation != self._generation:
                return False
            self._microphone_enabled = False
            self._shutdown_requested = True
            self._state = VoiceSessionState.STOPPED
        self._publish()
        return True

    def snapshot(self) -> VoiceSessionSnapshot:
        with self._lock:
            return VoiceSessionSnapshot(
                generation=self._generation,
                state=self._state,
                shutdown_requested=self._shutdown_requested,
                microphone_enabled=self._microphone_enabled,
            )

    def _publish(self) -> None:
        if self._on_state is not None:
            self._on_state(self.snapshot())
