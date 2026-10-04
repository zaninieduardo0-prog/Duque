"""Regras da conversa por voz do TELEX (pedido do Du, 03/10).

- "TELEX, boa tarde" → "Boa tarde, Du. À sua disposição." e fica 5 s esperando.
  Se o Du começar a falar, espera ele terminar (mesmo que demore minutos).
  Se ficar em silêncio: "Quer que eu continue de onde parei?" (só quando há
  conversa anterior). "Sim" → continua; "não" ou silêncio → standby.
- "TELEX" sozinho → bipe curto (sem falar) e escuta por 8 s; depois standby.
- "TELEX, <pedido>" tudo junto → faz e confirma curto ("Feito, senhor.").
- Enquanto ele fala, SÓ a palavra "TELEX" interrompe. Depois de interromper,
  escuta por 8 s; sem fala, standby.
- Ao terminar uma resposta → standby. Se terminou com pergunta ("O volume está
  bom?"), a resposta vale sem o nome por 5 s.

Este módulo é só a lógica (testável sem microfone). O runtime de voz
(duque_wake_v2.py) chama on_* e tick() e executa as ações devolvidas.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Literal

from .gate import addressed, is_sleep, is_stop, only_name, words

AFTER_GREETING_SECONDS = float(os.getenv("DUQUE_AFTER_GREETING", "5"))
LISTEN_SECONDS = float(os.getenv("DUQUE_LISTEN_SECONDS", "8"))
RESUME_ANSWER_SECONDS = float(os.getenv("DUQUE_RESUME_ANSWER", "5"))
FOLLOW_UP_SECONDS = float(os.getenv("DUQUE_FOLLOW_UP_SECONDS", "5"))
# Pausa curta no meio da fala não encerra o pedido: espera este tempo de
# silêncio depois do último trecho antes de responder.
END_OF_TURN_SECONDS = float(os.getenv("DUQUE_END_OF_TURN", "1.4"))

State = Literal["standby", "listening", "collecting", "ask_resume", "speaking"]
Action = Literal[
    "none", "ignore", "chime", "collect", "respond", "interrupt_and_listen", "interrupt_and_collect",
    "ask_resume", "resume", "standby", "sleep",
]

YES = frozenset({"sim", "pode", "continua", "continue", "claro", "isso", "quero", "manda", "bora", "ok", "beleza", "yes"})
NO = frozenset({"nao", "não", "deixa", "esquece", "negativo", "depois", "no"})


@dataclass
class VoiceFlow:
    clock: Callable[[], float] = time.monotonic
    state: State = "standby"
    deadline: float | None = None
    user_talking: bool = False
    greeting_pending: bool = False
    has_previous: bool = False
    awaiting_resume: bool = False
    collected: list[str] = field(default_factory=list)

    # entradas ----------------------------------------------------------------
    def _listen(self, seconds: float) -> None:
        self.state = "listening"
        self.deadline = self.clock() + seconds

    def on_greeting_done(self, has_previous: bool) -> Action:
        """Terminou de falar "Boa tarde, Du. À sua disposição."."""
        self.greeting_pending = True
        self.has_previous = has_previous
        self._listen(AFTER_GREETING_SECONDS)
        return "none"

    def on_call(self) -> Action:
        """Acordou do standby com "Telex" (ativação local)."""
        self.greeting_pending = False
        self._listen(LISTEN_SECONDS)
        return "chime"

    def on_speaking(self) -> None:
        self.state = "speaking"
        self.deadline = None

    def on_reply_done(self, spoken: str) -> Action:
        if self.awaiting_resume:
            # Acabou de perguntar "Quer que eu continue de onde parei?".
            self.awaiting_resume = False
            self.state, self.deadline = "ask_resume", self.clock() + RESUME_ANSWER_SECONDS
            return "none"
        if (spoken or "").strip().endswith("?"):
            self._listen(FOLLOW_UP_SECONDS)  # "O volume está bom?" → resposta sem o nome
            return "none"
        self.state, self.deadline = "standby", None
        return "standby"

    def on_speech_started(self) -> None:
        # Ele começou a falar: enquanto fala, nenhum prazo corre.
        if self.state in {"listening", "collecting", "ask_resume"}:
            self.user_talking = True

    def on_speech_stopped(self) -> None:
        self.user_talking = False
        if self.state == "collecting":
            self.deadline = self.clock() + END_OF_TURN_SECONDS

    def on_transcript(self, text: str) -> Action:
        """Uma fala do Du transcrita. Devolve o que o runtime deve fazer."""
        self.user_talking = False
        if not words(text):
            return "ignore"
        called = addressed(text)

        if self.state == "speaking":
            # Falando: SÓ "Telex" interrompe (nada de eco, barulho ou "para").
            if not called:
                return "ignore"
            if only_name(text) or is_stop(text):
                self._listen(LISTEN_SECONDS)
                return "interrupt_and_listen"
            self._collect(text)
            return "interrupt_and_collect"

        if called and is_sleep(text):
            self.state, self.deadline = "standby", None
            return "sleep"

        if self.state == "ask_resume":
            plain = set(words(text))
            if plain & YES and not plain & NO:
                self.state, self.deadline = "standby", None
                return "resume"
            if plain & NO or is_stop(text):
                self.state, self.deadline = "standby", None
                return "standby"
            self._collect(text)  # falou outra coisa: é um pedido novo
            return "collect"

        if called and only_name(text):
            self.greeting_pending = False
            self._listen(LISTEN_SECONDS)
            return "chime"

        if self.state in {"listening", "collecting"} or called:
            self.greeting_pending = False
            self._collect(text)
            return "collect"
        return "ignore"

    def _collect(self, text: str) -> None:
        self.state = "collecting"
        self.collected.append(text)
        self.deadline = self.clock() + END_OF_TURN_SECONDS

    def take_collected(self) -> str:
        text, self.collected = " ".join(self.collected).strip(), []
        return text

    def tick(self) -> Action:
        """Chamado algumas vezes por segundo: prazos que venceram."""
        if self.deadline is None or self.user_talking or self.clock() < self.deadline:
            return "none"
        if self.state == "collecting":
            self.state, self.deadline = "speaking", None
            return "respond"
        if self.state == "listening":
            if self.greeting_pending and self.has_previous:
                self.greeting_pending = False
                self.awaiting_resume = True
                self.state, self.deadline = "speaking", None  # ele vai perguntar
                return "ask_resume"
            self.greeting_pending = False
            self.state, self.deadline = "standby", None
            return "standby"
        if self.state == "ask_resume":
            self.state, self.deadline = "standby", None
            return "standby"
        return "none"


def greeting_reply(greeting: str, user: str = "Du") -> str:
    """"Boa tarde, TELEX." → "Boa tarde, Du. À sua disposição."."""
    match = re.match(r"\s*(bom dia|boa tarde|boa noite)", greeting or "", re.IGNORECASE)
    salutation = match.group(1).capitalize() if match else "Olá"
    return f"{salutation}, {user}. À sua disposição."
