from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, cast


@dataclass(slots=True)
class ModelResponse:
    text: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    raw: Any = None


class ModelAdapter(ABC):
    """Contrato único para qualquer modelo que dê inteligência ao Duque."""

    @abstractmethod
    def respond(self, messages: list[dict[str, str]], **kwargs: Any) -> ModelResponse:
        raise NotImplementedError


class NullModel(ModelAdapter):
    """Adapter offline para testes da arquitetura sem API ou internet."""

    def respond(self, messages: list[dict[str, str]], **kwargs: Any) -> ModelResponse:
        last = messages[-1]["content"] if messages else ""
        return ModelResponse(text=last)


class OpenAIResponsesModel(ModelAdapter):
    """Adapter opcional para a Responses API; a chave fica somente no ambiente."""

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        import os
        # Use a lower-latency default model; can be overridden with DUQUE_MODEL env var
        self.model = model or os.getenv("DUQUE_MODEL", "gpt-4o-mini")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY não configurada")

    def respond(self, messages: list[dict[str, str]], **kwargs: Any) -> ModelResponse:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Pacote openai não instalado") from exc

        client = OpenAI(api_key=self.api_key)
        response = client.responses.create(model=self.model, input=cast(Any, messages), **kwargs)
        text = getattr(response, "output_text", "") or ""
        return ModelResponse(text=text, raw=response)


class OllamaModel(ModelAdapter):
    """Cérebro local: um modelo rodando no próprio PC pelo Ollama (sem internet, sem créditos)."""

    def __init__(self, model: str | None = None, host: str | None = None, timeout: float | None = None) -> None:
        import os

        self.model = model or os.getenv("DUQUE_LOCAL_MODEL", "qwen2.5:3b")
        host = host or os.getenv("OLLAMA_HOST") or "http://127.0.0.1:11434"
        self.host = (host if "://" in host else f"http://{host}").rstrip("/")
        self.timeout = timeout if timeout is not None else float(os.getenv("DUQUE_LOCAL_TIMEOUT", "120"))

    def available(self) -> bool:
        """O Ollama está no ar e o modelo escolhido já foi baixado?"""
        import json
        import urllib.request

        try:
            with urllib.request.urlopen(f"{self.host}/api/tags", timeout=1.5) as response:
                names = [str(item.get("name", "")) for item in json.load(response).get("models", [])]
        except Exception:
            return False
        wanted = self.model if ":" in self.model else f"{self.model}:latest"
        return any(name == wanted or name.split(":")[0] == self.model for name in names)

    def respond(self, messages: list[dict[str, str]], **kwargs: Any) -> ModelResponse:
        import json
        import urllib.request

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "keep_alive": "30m",  # mantém o modelo na memória: a próxima resposta não paga o carregamento
            "options": {"temperature": 0.3, "num_ctx": 2048},
        }
        request = urllib.request.Request(
            f"{self.host}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            data = json.load(response)
        text = str((data.get("message") or {}).get("content", "")).strip()
        return ModelResponse(text=text, raw=data)


class ChainModel(ModelAdapter):
    """Tenta os modelos em ordem; se um falhar (sem crédito, sem rede), usa o próximo.

    Um modelo que falhou fica de castigo por ``cooldown`` segundos, para o Duque
    não esperar um timeout a cada pergunta.
    """

    def __init__(self, models: list[ModelAdapter], cooldown: float = 60.0, clock: Any = None) -> None:
        import time

        if not models:
            raise ValueError("ChainModel precisa de pelo menos um modelo")
        self.models = models
        self.cooldown = cooldown
        self._clock = clock or time.monotonic
        self._blocked_until: dict[int, float] = {}
        self.last_error: str | None = None

    def respond(self, messages: list[dict[str, str]], **kwargs: Any) -> ModelResponse:
        now = self._clock()
        candidates = [
            (index, model) for index, model in enumerate(self.models) if self._blocked_until.get(index, 0.0) <= now
        ] or list(enumerate(self.models))
        error: Exception | None = None
        for index, model in candidates:
            try:
                return model.respond(messages, **kwargs)
            except Exception as exc:
                error = exc
                self.last_error = f"{type(model).__name__}: {type(exc).__name__}: {exc}"
                self._blocked_until[index] = self._clock() + self.cooldown
        assert error is not None
        raise error


def default_model() -> ModelAdapter:
    """Escolhe o cérebro. DUQUE_BRAIN = auto (padrão) | local | openai.

    auto: modelo local se o Ollama estiver no ar, com a OpenAI de reserva (se houver
    chave); sem nenhum dos dois, o Duque segue só com as regras locais (NullModel).
    """
    import os

    mode = os.getenv("DUQUE_BRAIN", "auto").strip().casefold()
    chain: list[ModelAdapter] = []
    if mode in {"auto", "local", "ollama"}:
        local = OllamaModel()
        if mode != "auto" or local.available():
            chain.append(local)
    if mode in {"auto", "openai"} and os.getenv("OPENAI_API_KEY"):
        try:
            chain.append(OpenAIResponsesModel())
        except RuntimeError:
            pass
    if not chain:
        return NullModel()
    return chain[0] if len(chain) == 1 else ChainModel(chain)
