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


class LocalModel(ModelAdapter):
    """Adapter para modelos rodando localmente (opcional).

    Tenta usar backends open-source quando disponíveis (gpt4all ou llama_cpp).
    A presença do backend é verificada na inicialização e um erro claro é levantado
    se as dependências não estiverem instaladas. A configuração pode ser passada
    via variáveis de ambiente: DUQUE_LOCAL_BACKEND (gpt4all|llama) e
    DUQUE_LOCAL_MODEL_PATH.
    """

    def __init__(self, backend: str | None = None, model_path: str | None = None, *, timeout: int | None = None, max_retries: int | None = None) -> None:
        import os
        import logging

        self.log = logging.getLogger("duque.localmodel")
        self.backend = backend or os.getenv("DUQUE_LOCAL_BACKEND", "gpt4all")
        self.model_path = model_path or os.getenv("DUQUE_LOCAL_MODEL_PATH")
        # tempo limite em segundos para chamadas ao backend
        self.timeout = int(os.getenv("DUQUE_LOCAL_TIMEOUT", str(timeout or 30)))
        self.max_retries = int(os.getenv("DUQUE_LOCAL_RETRIES", str(max_retries or 2)))
        self._impl = None

        if self.backend == "gpt4all":
            try:
                from gpt4all import GPT4All

                # Inicializa com o modelo informado ou com o padrão do pacote
                self._impl = GPT4All(model=self.model_path) if self.model_path else GPT4All()
            except Exception as exc:
                self.log.exception("Falha ao inicializar gpt4all")
                raise RuntimeError(
                    "gpt4all não disponível. Instale o pacote 'gpt4all' e configure DUQUE_LOCAL_MODEL_PATH se necessário"
                ) from exc
        elif self.backend == "llama":
            try:
                from llama_cpp import Llama

                if not self.model_path:
                    raise RuntimeError("DUQUE_LOCAL_MODEL_PATH é obrigatório para o backend 'llama'")
                self._impl = Llama(model_path=self.model_path)
            except Exception as exc:
                self.log.exception("Falha ao inicializar llama_cpp")
                raise RuntimeError(
                    "llama_cpp não disponível. Instale 'llama-cpp-python' e configure DUQUE_LOCAL_MODEL_PATH"
                ) from exc
        else:
            raise RuntimeError(f"Backend local desconhecido: {self.backend}")

    def _call_impl(self, prompt: str, **kwargs: Any) -> Any:
        """Chama a implementação específica do backend e retorna a resposta bruta."""
        # Evita import no topo para não falhar em ambientes sem backend
        if self.backend == "gpt4all":
            # APIs do gpt4all podem expor 'generate' ou 'chat'
            if hasattr(self._impl, "generate"):
                return self._impl.generate(prompt, **kwargs)
            if hasattr(self._impl, "chat"):
                return self._impl.chat(prompt, **kwargs)
            # Fallback: tentar __call__
            return self._impl(prompt, **kwargs)

        if self.backend == "llama":
            # llama_cpp Llama é chamável e retorna dict-like com 'choices'
            return self._impl(prompt, **kwargs)

        raise RuntimeError(f"Backend desconhecido: {self.backend}")

    def _call_with_retries(self, prompt: str, **kwargs: Any) -> Any:
        import concurrent.futures
        import time

        last_exc: Exception | None = None
        for attempt in range(1, max(1, self.max_retries) + 1):
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                    fut = ex.submit(self._call_impl, prompt, **kwargs)
                    return fut.result(timeout=self.timeout)
            except concurrent.futures.TimeoutError as exc:
                last_exc = exc
                self.log.warning("Timeout ao chamar modelo local (attempt %d): %s", attempt, exc)
            except Exception as exc:
                last_exc = exc
                self.log.exception("Erro ao chamar modelo local (attempt %d)", attempt)
            # pequeno atraso entre tentativas
            time.sleep(0.5 * attempt)

        raise RuntimeError("Falha ao executar modelo local") from last_exc

    def respond(self, messages: list[dict[str, str]], **kwargs: Any) -> ModelResponse:
        # Monta um prompt simples a partir das mensagens
        prompt = "\n".join(m.get("content", "") for m in messages)
        try:
            raw = self._call_with_retries(prompt, **kwargs)
            # Normaliza formatos comuns
            if isinstance(raw, str):
                text = raw
            else:
                # gpt4all pode retornar objetos com 'response' ou 'generated_text'
                if hasattr(raw, "response"):
                    text = getattr(raw, "response")
                elif isinstance(raw, dict) and "choices" in raw:
                    choices = raw.get("choices") or []
                    if choices and isinstance(choices, (list, tuple)):
                        first = choices[0]
                        text = first.get("text") if isinstance(first, dict) else str(first)
                    else:
                        text = str(raw)
                else:
                    # Fallback genérico
                    text = str(raw)
            return ModelResponse(text=(text or "").strip(), raw=raw)
        except Exception as exc:
            self.log.exception("Erro ao gerar resposta local")
            raise RuntimeError("Erro ao executar modelo local: " + str(exc)) from exc
