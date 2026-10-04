"""Ouvido do TELEX no próprio PC: transforma a fala do Du em texto, sem API.

Padrão: o mesmo modelo Vosk em português que já faz a ativação (sem pacote
novo e leve para 6 GB de RAM), agora em modo livre. Se o pacote
``faster-whisper`` estiver instalado e DUQUE_STT=whisper, usa o Whisper, que
erra menos mas pesa mais.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable

SAMPLE_RATE = 16000


class VoskTranscriber:
    name = "vosk"

    def __init__(self, model: Any, recognizer_factory: Callable[..., Any]) -> None:
        self._model = model
        self._factory = recognizer_factory

    def transcribe(self, pcm: bytes) -> str:
        """Fala inteira (int16, 16 kHz, mono) → texto."""
        recognizer = self._factory(self._model, SAMPLE_RATE)
        step = 8000  # 250 ms por vez
        for start in range(0, len(pcm), step):
            recognizer.AcceptWaveform(pcm[start : start + step])
        try:
            return str(json.loads(recognizer.FinalResult() or "{}").get("text", "")).strip()
        except ValueError:
            return ""


class WhisperTranscriber:
    name = "whisper"

    def __init__(self, size: str = "base") -> None:
        from faster_whisper import WhisperModel  # type: ignore[import-not-found]

        self._model = WhisperModel(size, device="cpu", compute_type="int8")

    def transcribe(self, pcm: bytes) -> str:
        import numpy as np

        audio = np.frombuffer(pcm, dtype=np.int16).astype("float32") / 32768.0
        segments, _info = self._model.transcribe(audio, language="pt", beam_size=1, vad_filter=True)
        return " ".join(segment.text.strip() for segment in segments).strip()


def load(vosk_model: Any = None, log: Callable[[str], Any] = print) -> Any | None:
    """Escolhe o ouvido. ``vosk_model`` reaproveita o modelo já carregado pela ativação."""
    if os.getenv("DUQUE_STT", "vosk").strip().casefold() == "whisper":
        try:
            transcriber = WhisperTranscriber(os.getenv("DUQUE_WHISPER_SIZE", "base"))
            log("[STT] ouvido local: Whisper.")
            return transcriber
        except Exception as exc:
            log(f"[STT] Whisper indisponível ({type(exc).__name__}: {exc}); usando o Vosk.")
    try:
        import vosk  # type: ignore[import-not-found]

        if vosk_model is None:
            from . import local_wake

            model_dir = local_wake.find_model()
            if model_dir is None:
                log("[STT] modelo de português não encontrado; rode o preparar_duque.bat.")
                return None
            vosk.SetLogLevel(-1)
            vosk_model = vosk.Model(str(model_dir))
        log("[STT] ouvido local: Vosk.")
        return VoskTranscriber(vosk_model, vosk.KaldiRecognizer)
    except Exception as exc:
        log(f"[STT] ouvido local indisponível: {type(exc).__name__}: {exc}")
        return None
