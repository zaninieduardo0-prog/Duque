from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from typing import Any, Callable

from .perception import ScreenCapture


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    CHANGED_UNCONFIRMED = "changed_unconfirmed"
    NOT_CHANGED = "not_changed"
    FAILED = "failed"


class Observation:
    """Um olhar na tela: tamanho, impressão digital e (sob demanda) a descrição.

    A descrição (janela ativa, OCR, visão por modelo) só é calculada quando
    alguém a lê: o executor tira um "antes" e um "depois" a cada clique e só
    precisa comparar as impressões digitais. Antes, cada ação de interface
    rodava OCR/visão duas vezes (lento e, com visão por modelo, caro).
    """

    __slots__ = ("width", "height", "fingerprint", "source", "_description", "_describe")

    def __init__(
        self,
        width: int,
        height: int,
        fingerprint: str,
        source: str = "screen",
        description: dict[str, Any] | None = None,
        *,
        describe: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.width = width
        self.height = height
        self.fingerprint = fingerprint
        self.source = source
        self._description = description
        self._describe = describe if description is None else None

    @property
    def description(self) -> dict[str, Any] | None:
        if self._describe is not None:
            describe, self._describe = self._describe, None
            try:
                self._description = describe()
            except Exception as exc:
                self._description = {"visual_analysis": {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}}
        return self._description

    @property
    def available(self) -> bool:
        return bool(self.fingerprint)

    def __repr__(self) -> str:
        return f"Observation({self.width}x{self.height}, {self.fingerprint[:12]!r}, source={self.source!r})"


@dataclass(slots=True, frozen=True)
class VerificationResult:
    status: VerificationStatus
    changed: bool
    before: Observation
    after: Observation
    reason: str
    confidence: float = 0.0

    @property
    def verified(self) -> bool:
        return self.status == VerificationStatus.VERIFIED


def fingerprint_of(capture: ScreenCapture) -> str:
    image = capture.image
    try:
        payload = image.tobytes()
    except AttributeError:
        payload = repr(image).encode("utf-8", errors="replace")
    return sha256(payload).hexdigest()


def observe(
    capture: ScreenCapture,
    description: dict[str, Any] | None = None,
    *,
    describe: Callable[[], dict[str, Any]] | None = None,
) -> Observation:
    return Observation(capture.width, capture.height, fingerprint_of(capture), capture.source, description, describe=describe)


def compare(before: Observation, after: Observation) -> VerificationResult:
    if not before.available or not after.available:
        # Sem captura não há como saber: NÃO declara "nada mudou" (isso fazia o
        # agente repetir a ação e digitar/clicar em dobro).
        return VerificationResult(
            VerificationStatus.FAILED, True, before, after, "Não foi possível capturar a tela para conferir", 0.0,
        )
    changed = before.fingerprint != after.fingerprint
    status = VerificationStatus.CHANGED_UNCONFIRMED if changed else VerificationStatus.NOT_CHANGED
    reason = "A tela mudou, mas o resultado esperado não foi confirmado" if changed else "Nenhuma mudança visual detectada"
    return VerificationResult(status, changed, before, after, reason, 0.0)


class Verification:
    """Observa o computador e permite validar resultado por mudança ou condição semântica."""

    def __init__(self, perception: Any, *, settle_seconds: float = 1.5, poll_seconds: float = 0.25,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> None:
        self.perception = perception
        self.settle_seconds = settle_seconds
        self.poll_seconds = poll_seconds
        self.sleep = sleep
        self.clock = clock

    def snapshot(self) -> Observation:
        """Captura a tela; a descrição (OCR/visão) só roda se alguém ler ``description``."""
        try:
            capture = self.perception.screenshot()
        except Exception as exc:
            error = {"visual_analysis": {"status": "failed", "error": f"Captura de tela: {type(exc).__name__}: {exc}"}}
            return Observation(0, 0, "", "screen", error)
        return observe(capture, describe=lambda: self.perception.describe(capture))

    def wait_for_change(self, before: Observation, timeout: float | None = None) -> Observation:
        """Olha de novo até a tela mudar (ou o tempo acabar).

        A tela leva alguns centésimos para reagir a um clique/tecla: comparar
        logo em seguida dava "nada mudou" falso, e o agente repetia a ação.
        """
        limit = self.settle_seconds if timeout is None else max(0.0, float(timeout))
        deadline = self.clock() + limit
        while True:
            after = self.snapshot()
            if not after.available or not before.available or after.fingerprint != before.fingerprint:
                return after
            if self.clock() >= deadline:
                return after
            self.sleep(self.poll_seconds)

    def verify_change(self, before: Observation, timeout: float | None = None) -> VerificationResult:
        return compare(before, self.wait_for_change(before, timeout))

    def verify(
        self,
        before: Observation,
        *,
        expected: Callable[[Observation], bool] | None = None,
        confidence: float = 1.0,
    ) -> VerificationResult:
        after = self.wait_for_change(before)
        if expected is None or not after.available:
            return compare(before, after)
        changed = before.fingerprint != after.fingerprint
        try:
            matched = bool(expected(after))
        except Exception as exc:
            return VerificationResult(
                VerificationStatus.FAILED,
                changed,
                before,
                after,
                f"Falha ao avaliar resultado esperado: {type(exc).__name__}: {exc}",
                0.0,
            )
        if matched:
            return VerificationResult(
                VerificationStatus.VERIFIED,
                changed,
                before,
                after,
                "Resultado esperado confirmado",
                max(0.0, min(1.0, float(confidence))),
            )
        status = VerificationStatus.CHANGED_UNCONFIRMED if changed else VerificationStatus.NOT_CHANGED
        return VerificationResult(
            status,
            changed,
            before,
            after,
            "Resultado esperado não confirmado",
            0.0,
        )
