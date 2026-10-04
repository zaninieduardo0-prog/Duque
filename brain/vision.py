from __future__ import annotations

import base64
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, cast


@dataclass(slots=True)
class VisionResponse:
    text: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    raw: Any = None


class VisionAdapter(ABC):
    """Contrato provider-agnostic para análise de imagens."""

    @abstractmethod
    def analyze(self, image: Any, prompt: str, **kwargs: Any) -> VisionResponse:
        raise NotImplementedError


class NullVisionAdapter(VisionAdapter):
    """Adapter seguro que não envia imagens nem inventa percepção."""

    def analyze(self, image: Any, prompt: str, **kwargs: Any) -> VisionResponse:
        return VisionResponse(
            data={"status": "unavailable", "reason": "vision_adapter_not_configured"}
        )


class OpenAIResponsesVisionAdapter(VisionAdapter):
    """Visão via Responses API, ativada explicitamente pelo runtime."""

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        self.model = model or os.getenv("DUQUE_VISION_MODEL", "")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        if not self.model:
            raise ValueError("DUQUE_VISION_MODEL não configurado")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY não configurada")
        try:
            self.timeout = float(os.getenv("DUQUE_VISION_TIMEOUT", "60"))
        except ValueError:
            self.timeout = 60.0
        self._client: Any = None

    def _get_client(self) -> Any:
        # Um cliente só, com timeout: antes era um por imagem e sem limite de espera.
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise RuntimeError("A visão OpenAI requer o pacote openai") from exc
            self._client = OpenAI(api_key=self.api_key, timeout=self.timeout, max_retries=1)
        return self._client

    def analyze(self, image: Any, prompt: str, **kwargs: Any) -> VisionResponse:
        client = self._get_client()
        data_url = _image_data_url(image)
        response = client.responses.create(
            model=self.model,
            input=cast(Any, [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": data_url},
                    ],
                }
            ]),
        )
        text = getattr(response, "output_text", "") or ""
        return VisionResponse(text=text, raw=response)


def _image_data_url(image: Any) -> str:
    """Converte uma imagem PIL-like em data URL PNG sem criar arquivo temporário."""
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"
