"""Compatibilidade: o adapter da OpenAI vive em brain.model.OpenAIResponsesModel.

Antes existiam duas implementações quase iguais; agora há uma só.
"""

from __future__ import annotations

from ..model import OpenAIResponsesModel

OpenAIAdapter = OpenAIResponsesModel

__all__ = ["OpenAIAdapter"]
