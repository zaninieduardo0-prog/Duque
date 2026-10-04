"""Liga a conversa local (voice/local_session.py) ao microfone, alto-falante e cérebro reais."""

from __future__ import annotations

import os
import time
from typing import Any, Callable

from . import local_stt, local_tts
from .local_session import FRAME_SAMPLES, SAMPLE_RATE, Deps, LocalSession


def voice_mode(has_openai_key: bool, openai_blocked: bool = False) -> str:
    """"local" ou "openai". DUQUE_VOICE = auto (padrão) | local | openai.

    auto: voz da OpenAI só quando há chave e ela está funcionando; sem chave, ou depois
    de "sem créditos", a conversa é local.
    """
    chosen = os.getenv("DUQUE_VOICE", "auto").strip().casefold()
    if chosen in {"local", "openai"}:
        return chosen
    return "openai" if has_openai_key and not openai_blocked else "local"


class LocalVoice:
    """Carrega ouvido e voz uma vez e roda uma conversa por ativação."""

    def __init__(
        self,
        *,
        think: Callable[[str], str],
        record: Callable[[str, str], None],
        log: Callable[[str], Any],
        hud: Callable[[str, str], None],
        chime: Callable[[], None],
        device_index: Callable[[], int],
        vosk_model: Any = None,
        control: Callable[[str], bool] | None = None,
    ) -> None:
        self._args: dict[str, Any] = dict(think=think, record=record, log=log, hud=hud, chime=chime)
        if control is not None:
            self._args["control"] = control
        self._device_index = device_index
        self._vosk_model = vosk_model
        self._log = log
        self._stt: Any = None
        self._tts: Any = None
        self._loaded = False

    def load(self) -> bool:
        if not self._loaded:
            self._stt = local_stt.load(self._vosk_model, self._log)
            self._tts = local_tts.load(self._log)
            self._loaded = True
        if self._stt is None:
            self._log("[VOZ-LOCAL] sem ouvido local (modelo Vosk); rode o preparar_duque.bat.")
        if self._tts is None:
            self._log("[VOZ-LOCAL] sem voz local; rode o preparar_local.bat.")
        return self._stt is not None and self._tts is not None

    def run(self, greeting: str | None = None, *, call: bool = False, preroll: bytes = b"") -> str:
        import numpy as np
        import sounddevice as sd
        from pvrecorder import PvRecorder

        if not self.load():
            return "indisponível"
        hud = self._args["hud"]
        recorder = PvRecorder(frame_length=FRAME_SAMPLES, device_index=self._device_index())
        recorder.start()
        log = self._log

        def read_frame() -> bytes:
            return np.asarray(recorder.read(), dtype=np.int16).tobytes()

        def mute() -> None:
            try:
                recorder.stop()
            except Exception:
                pass

        def unmute() -> None:
            try:
                recorder.start()
            except Exception as exc:
                log(f"[VOZ-LOCAL] microfone não reiniciou: {exc}")

        def play(audio: local_tts.Audio) -> None:
            sd.play(np.frombuffer(audio.pcm, dtype=np.int16), audio.sample_rate)
            # Nunca espera para sempre: se o alto-falante sumir no meio da fala,
            # sd.wait() travava a conversa local (e a ativação por voz) de vez.
            limit = time.monotonic() + audio.seconds + 5.0
            while time.monotonic() < limit:
                try:
                    active = bool(sd.get_stream().active)
                except Exception:
                    active = False
                if not active:
                    break
                time.sleep(0.05)
            else:
                log("[VOZ-LOCAL] o alto-falante não terminou de tocar; seguindo.")
                sd.stop()

        deps = Deps(
            read_frame=read_frame,
            transcribe=self._stt.transcribe,
            synthesize=self._tts.synthesize,
            play=play,
            mute_mic=mute,
            unmute_mic=unmute,
            **self._args,  # type: ignore[arg-type]
        )
        try:
            log(f"[VOZ-LOCAL] conversa local iniciada ({self._stt.name} + {self._tts.name}).")
            reason = LocalSession(deps).converse(greeting, call=call, preroll=preroll)
            log(f"[VOZ-LOCAL] conversa local encerrada ({reason}).")
            return reason
        except Exception:
            hud("erro", "Conversa local falhou — veja o duque.log")
            raise
        finally:
            try:
                recorder.stop()
                recorder.delete()
            except Exception:
                pass


__all__ = ["LocalVoice", "voice_mode", "SAMPLE_RATE"]
