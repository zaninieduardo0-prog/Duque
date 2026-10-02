"""Extrai falas (do Du e do Duque) dos eventos da sessão Realtime.

O SDK entrega as transcrições por caminhos diferentes conforme a versão:
eventos de modelo já tipados ou o evento bruto do servidor. Este módulo
reconhece os dois, para registrar a voz na conversa compartilhada.
"""

from __future__ import annotations

from typing import Any

USER_RAW = {"conversation.item.input_audio_transcription.completed"}
ASSISTANT_RAW = {"response.output_audio_transcript.done", "response.output_text.done"}


def _field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def speech_from_event(event: Any) -> tuple[str, str] | None:
    """Retorna (papel, texto) quando o evento contém uma fala completa."""
    if _field(event, "type") != "raw_model_event":
        return None
    data = _field(event, "data")
    kind = _field(data, "type") or ""

    if kind == "input_audio_transcription_completed":
        text = _field(data, "transcript")
        return ("user", str(text).strip()) if text else None

    payload = _field(data, "data") if kind == "raw_server_event" else data
    payload_type = _field(payload, "type") or ""
    if payload_type in USER_RAW:
        text = _field(payload, "transcript")
        return ("user", str(text).strip()) if text else None
    if payload_type in ASSISTANT_RAW:
        text = _field(payload, "transcript") or _field(payload, "text")
        return ("assistant", str(text).strip()) if text else None
    return None
