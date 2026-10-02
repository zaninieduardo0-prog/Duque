from __future__ import annotations

import os

from ..model import ModelAdapter, OpenAIResponsesModel


def create_developer_model() -> ModelAdapter | None:
    """Escolhe o cérebro programador da Forja.

    DUQUE_DEV_PROVIDER = anthropic | openai | auto (padrão). No modo auto, usa
    Claude se ANTHROPIC_API_KEY existir, senão OpenAI, senão nenhum (a Forja
    fica desativada em vez de improvisar com um modelo offline).
    """
    provider = os.getenv("DUQUE_DEV_PROVIDER", "auto").strip().casefold()
    if provider in {"anthropic", "claude"} or (provider == "auto" and os.getenv("ANTHROPIC_API_KEY")):
        from .anthropic_provider import ClaudeAdapter

        return ClaudeAdapter()
    if provider == "openai" or (provider == "auto" and os.getenv("OPENAI_API_KEY")):
        return OpenAIResponsesModel(model=os.getenv("DUQUE_DEV_MODEL") or None)
    return None
