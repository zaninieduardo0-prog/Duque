"""Portão de audição: o TELEX só responde quando é chamado.

Regras (pedido do Du):
- (sem saudação: o nome "TELEX" é a única ativação)
- "Telex" sozinho → fica ouvindo por alguns segundos o pedido.
- "Telex, <pedido>" → responde direto. Depois de responder, standby de novo.
- Depois de cada pedido a audição "trava": falas de fundo são ignoradas até
  ele dizer "Telex" de novo.
- "Telex, stop" (ou só "Telex" enquanto ele fala) interrompe na hora.
- "Repousar, Telex" volta ao standby na hora.
- Se o TELEX terminar com uma pergunta, a próxima frase vale por alguns
  segundos sem precisar do nome.
"""

from __future__ import annotations

import os
import re
import time
import unicodedata
from dataclasses import dataclass
from threading import Lock
from typing import Callable, Literal

# Um nome só: TELEX (a transcrição às vezes escreve "Teles", "Télex" ou "Tele X").
TELEX_NAMES = frozenset({"telex", "teles", "telecs", "teleks", "telexi", "talex", "telax"})
WAKE_NAMES = TELEX_NAMES
SLEEP_WORDS = frozenset({"repousar", "repousa", "repouse", "repouso", "repousando"})
STOP_WORDS = frozenset({
    "stop", "stopa", "para", "pare", "parar", "chega", "silencio", "cala", "calaboca", "quieto",
    "cancela", "cancelar", "esquece", "espera", "pausa", "basta", "shh", "psiu",
})
# Palavras que podem acompanhar o "parar" ("Telex, para de falar aí").
STOP_EXTRA = frozenset({"de", "falar", "fala", "ai", "isso", "tudo", "um", "pouco", "momento", "minuto"})
FILLER = frozenset({"ei", "hey", "hei", "oi", "ok", "okay", "o", "a", "por", "favor", "agora", "ja", "e", "boca"})

OPEN_SECONDS = float(os.getenv("DUQUE_OPEN_SECONDS", "12"))
FOLLOW_UP_SECONDS = float(os.getenv("DUQUE_FOLLOW_UP_SECONDS", "8"))
# "Telex" sozinho: por quanto tempo ele fica ouvindo o pedido.
LISTEN_SECONDS = float(os.getenv("DUQUE_LISTEN_SECONDS", "8"))
# Responder sem o nome quando o TELEX terminou com uma pergunta. Desligado:
# o Du quer que só o nome reative (DUQUE_FOLLOW_UP=1 religa).
FOLLOW_UP_ENABLED = os.getenv("DUQUE_FOLLOW_UP", "0").casefold() in {"1", "true", "yes", "on", "sim"}

Action = Literal["ignore", "stop", "respond", "sleep", "listen"]


def words(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", (text or "").casefold())
    plain = "".join(char for char in normalized if not unicodedata.combining(char))
    plain = re.sub(r"\btele[\s-]*(x|xis|ex|cs|ks)\b", "telex", plain)
    return re.findall(r"[a-z0-9]+", plain)


def addressed(text: str) -> bool:
    return any(word in WAKE_NAMES for word in words(text))


def is_stop(text: str) -> bool:
    """Só o nome + palavras de parar ("Telex, stop", "para, Telex", "Telex, chega")."""
    rest = [word for word in words(text) if word not in WAKE_NAMES and word not in FILLER]
    return (
        any(word in STOP_WORDS for word in rest)
        and all(word in STOP_WORDS or word in STOP_EXTRA for word in rest)
    )


def is_sleep(text: str) -> bool:
    """ "Repousar, Telex" (só isso, com ou sem "agora")."""
    rest = [word for word in words(text) if word not in WAKE_NAMES and word not in FILLER]
    return bool(rest) and all(word in SLEEP_WORDS for word in rest)


def only_name(text: str) -> bool:
    tokens = words(text)
    return bool(tokens) and all(word in WAKE_NAMES or word in FILLER for word in tokens)


@dataclass(slots=True, frozen=True)
class Decision:
    action: Action
    reason: str


class ListenGate:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._open_until = 0.0
        self._lock = Lock()

    def open(self, seconds: float = OPEN_SECONDS) -> None:
        with self._lock:
            self._open_until = self._clock() + max(0.0, seconds)

    def close(self) -> None:
        with self._lock:
            self._open_until = 0.0

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._clock() < self._open_until

    def decide(self, transcript: str, *, speaking: bool = False) -> Decision:
        """Decide o que fazer com uma fala transcrita e já trava a audição."""
        if not words(transcript):
            return Decision("ignore", "vazio")
        called = addressed(transcript)
        if (called or self.is_open) and is_sleep(transcript):
            self.close()
            return Decision("sleep", "pediu para repousar")
        if (called or self.is_open) and is_stop(transcript):
            self.close()
            return Decision("stop", "pediu para parar")
        if called and speaking and only_name(transcript):
            # Chamou pelo nome enquanto ele falava: para na hora e escuta.
            self.open(LISTEN_SECONDS)
            return Decision("stop", "chamado durante a fala")
        if called and only_name(transcript):
            # Só "Telex": abre a escuta por alguns segundos, sem responder nada.
            self.open(LISTEN_SECONDS)
            return Decision("listen", "chamado só pelo nome")
        if called:
            self.close()
            return Decision("respond", "chamado pelo nome")
        if speaking:
            # Enquanto ele fala, o microfone também ouve o alto-falante: sem o nome,
            # é eco (ou conversa de fundo). O ouvido continua aberto para depois.
            return Decision("ignore", "durante a fala, sem o nome (eco)")
        if self.is_open:
            self.close()
            return Decision("respond", "audição aberta")
        return Decision("ignore", "sem o nome: som de fundo")


def is_echo(heard: str, spoken: str, threshold: float = 0.6) -> bool:
    """A "fala do Du" é, na verdade, o microfone ouvindo a última resposta do TELEX?"""
    heard_words = [word for word in words(heard) if len(word) > 2]
    spoken_words = set(word for word in words(spoken) if len(word) > 2)
    if len(heard_words) < 2 or not spoken_words:
        return False
    hits = sum(1 for word in heard_words if word in spoken_words)
    return hits / len(heard_words) >= threshold


def ends_with_question(text: str) -> bool:
    return (text or "").strip().endswith("?")
