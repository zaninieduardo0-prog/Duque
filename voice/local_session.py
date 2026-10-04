"""Conversa por voz 100% local do TELEX (sem Realtime, sem créditos).

    ouve (microfone → pausa na fala) → transcreve (Vosk/Whisper) →
    pensa (AgentLoop: regras + Ollama) → fala (Piper/SAPI)

Segue as mesmas regras da conversa de antes (voice/conversation_flow.py):
- "Bom dia, TELEX" → "Bom dia, Du. À sua disposição." e escuta 5 s;
- "TELEX" sozinho → bipe e escuta 8 s; sem fala, volta ao standby;
- "TELEX, <pedido>" → faz e responde; depois standby;
- se a resposta termina em pergunta, a próxima fala vale sem o nome;
- "Repousar" / "para" encerram.

Tudo que toca em microfone, alto-falante, modelo e voz entra por ``Deps``, então
a lógica é testável sem nada disso.
"""

from __future__ import annotations

import array
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from .conversation_flow import greeting_reply
from .gate import addressed, is_sleep, is_stop, only_name, words
from .local_wake import boost
from .local_tts import Audio

SAMPLE_RATE = 16000
FRAME_SAMPLES = 1280  # 80 ms, igual ao da ativação
FRAME_SECONDS = FRAME_SAMPLES / SAMPLE_RATE
FRAME_BYTES = FRAME_SAMPLES * 2

AFTER_GREETING_SECONDS = float(os.getenv("DUQUE_AFTER_GREETING", "5"))
LISTEN_SECONDS = float(os.getenv("DUQUE_LISTEN_SECONDS", "8"))
FOLLOW_UP_SECONDS = float(os.getenv("DUQUE_FOLLOW_UP_SECONDS", "8"))
# Silêncio depois da última palavra para considerar o pedido terminado.
END_SILENCE_SECONDS = float(os.getenv("DUQUE_END_OF_TURN", "1.1"))
MAX_UTTERANCE_SECONDS = 25.0
MIN_SPEECH_LEVEL = float(os.getenv("DUQUE_SPEECH_LEVEL", "0.02"))
MAX_EMPTY_TURNS = 2
# Resposta muito longa (lista de arquivos, pesquisa) não é lida inteira em voz alta.
MAX_SPOKEN_CHARS = int(os.getenv("DUQUE_MAX_SPOKEN_CHARS", "500"))

_NAME = re.compile(r"\b(?:t[eé]l[eé](?:x|cs|ks|s|xi)|tele[\s-]*x|talex|telax)\b[\s,.!?:;-]*", re.IGNORECASE)


def strip_name(text: str) -> str:
    """Tira o nome do TELEX da frase, mantendo acentos e o resto como foi dito."""
    return re.sub(r"\s+", " ", _NAME.sub(" ", text or "")).strip(" ,.;:!?-")


def _level(frame: bytes) -> float:
    samples = array.array("h")
    samples.frombytes(frame[: len(frame) - len(frame) % 2])
    if not samples:
        return 0.0
    return (sum(sample * sample for sample in samples) / len(samples)) ** 0.5 / 32768.0


@dataclass
class Deps:
    read_frame: Callable[[], bytes]  # 1280 amostras int16 de 16 kHz; bloqueia até haver áudio
    transcribe: Callable[[bytes], str]
    synthesize: Callable[[str], Audio]
    play: Callable[[Audio], None]  # bloqueia até terminar de falar
    think: Callable[[str], str]  # pedido → resposta (o cérebro do Duque)
    chime: Callable[[], None] = lambda: None
    hud: Callable[[str, str], None] = lambda _state, _text="": None
    log: Callable[[str], Any] = print
    record: Callable[[str, str], None] = lambda _role, _text: None
    # Antes/depois de falar: o microfone não pode guardar o que o alto-falante disse.
    mute_mic: Callable[[], None] = lambda: None
    unmute_mic: Callable[[], None] = lambda: None
    # Comandos de controle ("Telex, pausa tudo"): devolve True se tratou. Sem isto a
    # pausa de emergência por voz só encerrava a conversa local (caía no "parar").
    control: Callable[[str], bool] = lambda _text: False


@dataclass
class LocalSession:
    deps: Deps
    _peak: float = field(default=0.0, init=False)

    # captura -----------------------------------------------------------------
    def capture(self, wait_seconds: float, preroll: bytes = b"") -> bytes:
        """Espera a fala começar (até ``wait_seconds``) e devolve até a pausa. Vazio = ninguém falou."""
        frames: list[bytes] = []
        speaking = False
        silent = 0
        waited = 0.0
        floor = None
        end_silence_frames = max(1, int(END_SILENCE_SECONDS / FRAME_SECONDS))
        max_frames = int(MAX_UTTERANCE_SECONDS / FRAME_SECONDS)
        pending = [preroll[i : i + FRAME_BYTES] for i in range(0, len(preroll), FRAME_BYTES)]

        while True:
            live = not pending
            if pending:
                frame = pending.pop(0)
                if len(frame) < FRAME_BYTES:
                    frame = frame + b"\0" * (FRAME_BYTES - len(frame))
            else:
                frame = self.deps.read_frame()
                if not frame:
                    break
            frame, self._peak = boost(frame, self._peak)
            level = _level(frame)
            if live and not speaking:
                # Piso de ruído do ambiente (só em áudio ao vivo e fora da fala; limitado
                # para que uma fala logo no início não vire "ruído").
                floor = min(level, 0.05) if floor is None else min(floor * 1.02, level, 0.05)
            threshold = max(MIN_SPEECH_LEVEL, (floor or 0.0) * 3.0)
            if level >= threshold:
                speaking, silent = True, 0
            elif speaking:
                silent += 1
            if speaking:
                frames.append(frame)
                if silent >= end_silence_frames or len(frames) >= max_frames:
                    break
            elif not pending:
                waited += FRAME_SECONDS
                if waited >= wait_seconds:
                    break
        return b"".join(frames) if speaking else b""

    # fala --------------------------------------------------------------------
    @staticmethod
    def shorten(text: str) -> str:
        """Corta no fim de uma frase e avisa que o resto está na tela."""
        text = text.strip()
        if len(text) <= MAX_SPOKEN_CHARS:
            return text
        cut = text[:MAX_SPOKEN_CHARS]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "), cut.rfind("\n"))
        head = cut[: end + 1] if end > MAX_SPOKEN_CHARS // 3 else cut.rsplit(" ", 1)[0]
        return head.rstrip() + " O resto está na tela."

    def chime(self) -> None:
        """Bipe com o microfone fechado: ele não pode ouvir o próprio bipe como se fosse fala."""
        self.deps.mute_mic()
        try:
            self.deps.chime()
        finally:
            self.deps.unmute_mic()

    def say(self, text: str) -> None:
        text = self.shorten(text)
        if not text:
            return
        deps = self.deps
        deps.mute_mic()
        try:
            audio = deps.synthesize(text)
            if audio.pcm:
                deps.hud("falando", "TELEX falando...")
                deps.play(audio)
        except Exception as exc:
            deps.log(f"[VOZ-LOCAL] não consegui falar: {type(exc).__name__}: {exc}")
        finally:
            deps.unmute_mic()

    # conversa ----------------------------------------------------------------
    def converse(self, greeting: str | None = None, *, call: bool = False, preroll: bytes = b"") -> str:
        """Roda uma conversa até o standby. Devolve o motivo do fim ("silêncio", "repousar", "pedido"...)."""
        deps = self.deps
        deps.hud("ouvindo", "Escutando você...")
        if greeting:
            self.say(greeting_reply(greeting))
            window = AFTER_GREETING_SECONDS
        else:
            self.chime()
            window = LISTEN_SECONDS
        pending, empty, reason = preroll if call else b"", 0, "silêncio"
        while True:
            deps.hud("ouvindo", "Pode falar...")
            pcm = self.capture(window, pending)
            pending = b""
            if not pcm:
                break
            deps.hud("processando", "Entendendo...")
            try:
                text = deps.transcribe(pcm).strip()
            except Exception as exc:
                deps.log(f"[VOZ-LOCAL] transcrição falhou: {type(exc).__name__}: {exc}")
                text = ""
            deps.log(f"[VOZ-LOCAL] ouvi: {text!r}")
            if not words(text):
                empty += 1
                if empty >= MAX_EMPTY_TURNS:
                    break
                window = LISTEN_SECONDS
                continue
            try:
                handled = deps.control(text)
            except Exception as exc:
                deps.log(f"[VOZ-LOCAL] comando de controle falhou: {type(exc).__name__}: {exc}")
                handled = False
            if handled:
                reason = "controle"
                break
            if is_sleep(text):
                reason = "repousar"
                break
            if is_stop(text):
                reason = "parar"
                break
            if only_name(text) or not strip_name(text):
                self.chime()
                window = LISTEN_SECONDS
                continue
            request = strip_name(text) if addressed(text) else text
            deps.record("user", request)
            deps.hud("processando", "Processando comando...")
            try:
                reply = deps.think(request).strip()
            except Exception as exc:
                deps.log(f"[VOZ-LOCAL] o cérebro falhou: {type(exc).__name__}: {exc}")
                reply = "Tive um problema para pensar nisso agora."
            deps.record("assistant", reply)
            self.say(reply)
            if reply.endswith("?"):
                window = FOLLOW_UP_SECONDS  # "O volume está bom?" → resposta sem o nome
                continue
            reason = "pedido"
            break
        deps.hud("standby", "Sistema online")
        return reason
