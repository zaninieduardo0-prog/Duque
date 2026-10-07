"""A IA que comanda o TELEX: um laço de ferramentas, com Claude ou OpenAI.

Escolha (variável TELEX_IA): "claude", "openai" ou vazio = automático
(Claude se houver ANTHROPIC_API_KEY, senão OpenAI).
"""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

MAX_STEPS = int(os.getenv("TELEX_MAX_PASSOS", "25"))
CLAUDE_MODEL = os.getenv("TELEX_MODELO_CLAUDE", "claude-opus-5-5")
OPENAI_MODEL = os.getenv("TELEX_MODELO_OPENAI", "gpt-4.1")
# Pedidos de voz precisam de resposta rápida; "medium"/"high" pensam mais.
CLAUDE_EFFORT = os.getenv("TELEX_ESFORCO", "low")


@dataclass(slots=True)
class ToolOutput:
    text: str
    image_png: bytes | None = None
    is_error: bool = False


@dataclass(slots=True)
class Tool:
    name: str
    description: str
    properties: dict[str, Any] = field(default_factory=dict)
    required: tuple[str, ...] = ()
    function: Callable[..., Any] | None = None

    def schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": self.properties, "required": list(self.required)}


ToolRunner = Callable[[str, dict[str, Any]], ToolOutput]
History = list[tuple[str, str]]  # (pergunta, resposta) dos últimos pedidos


@dataclass(slots=True)
class Reply:
    text: str
    steps: int = 0
    tools_used: list[str] = field(default_factory=list)
    failed: bool = False


def provider_name() -> str:
    choice = os.getenv("TELEX_IA", "").strip().casefold()
    if choice in {"claude", "anthropic"}:
        return "claude"
    if choice in {"openai", "gpt"}:
        return "openai"
    return "claude" if os.getenv("ANTHROPIC_API_KEY") else "openai"


class ClaudeBrain:
    """Laço manual de ferramentas na API do Claude (o TELEX executa as ferramentas no PC)."""

    def __init__(self, client: Any = None, model: str = CLAUDE_MODEL, effort: str = CLAUDE_EFFORT) -> None:
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self.client = client
        self.model = model
        self.effort = effort

    def run(self, system: str, history: History, text: str, tools: list[Tool], runner: ToolRunner) -> Reply:
        messages: list[dict[str, Any]] = []
        for question, answer in history:
            messages += [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
        messages.append({"role": "user", "content": text})
        specs = [{"name": tool.name, "description": tool.description, "input_schema": tool.schema()} for tool in tools]
        reply = Reply("")
        for _ in range(MAX_STEPS):
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                tools=specs,
                messages=messages,
                output_config={"effort": self.effort},
                # Se um filtro de segurança recusar por engano, outro modelo responde.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
            if response.stop_reason == "refusal":
                reply.text = "Não posso ajudar com isso, Du."
                reply.failed = True
                return reply
            messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason == "pause_turn":
                continue
            calls = [block for block in response.content if block.type == "tool_use"]
            if not calls:
                reply.text = " ".join(block.text for block in response.content if block.type == "text").strip()
                return reply
            results = []
            for call in calls:
                reply.steps += 1
                reply.tools_used.append(call.name)
                output = runner(call.name, dict(call.input or {}))
                content: list[dict[str, Any]] = []
                if output.image_png is not None:
                    content.append({
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(output.image_png).decode()},
                    })
                content.append({"type": "text", "text": output.text or "ok"})
                results.append({"type": "tool_result", "tool_use_id": call.id, "content": content, "is_error": output.is_error})
            messages.append({"role": "user", "content": results})
        reply.text = "Fiz várias tentativas e não terminei, Du. Me diga como prefere seguir."
        reply.failed = True
        return reply


class OpenAIBrain:
    """O mesmo laço com a OpenAI (Chat Completions + function calling)."""

    def __init__(self, client: Any = None, model: str = OPENAI_MODEL) -> None:
        if client is None:
            from openai import OpenAI

            client = OpenAI()
        self.client = client
        self.model = model

    def run(self, system: str, history: History, text: str, tools: list[Tool], runner: ToolRunner) -> Reply:
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for question, answer in history:
            messages += [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
        messages.append({"role": "user", "content": text})
        specs = [
            {"type": "function", "function": {"name": tool.name, "description": tool.description, "parameters": tool.schema()}}
            for tool in tools
        ]
        reply = Reply("")
        for _ in range(MAX_STEPS):
            response = self.client.chat.completions.create(model=self.model, messages=messages, tools=specs)
            message = response.choices[0].message
            calls = message.tool_calls or []
            if not calls:
                reply.text = (message.content or "").strip()
                return reply
            messages.append({
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    {"id": call.id, "type": "function", "function": {"name": call.function.name, "arguments": call.function.arguments}}
                    for call in calls
                ],
            })
            images: list[bytes] = []
            for call in calls:
                reply.steps += 1
                reply.tools_used.append(call.function.name)
                try:
                    arguments = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                output = runner(call.function.name, arguments if isinstance(arguments, dict) else {})
                messages.append({"role": "tool", "tool_call_id": call.id, "content": output.text or "ok"})
                if output.image_png is not None:
                    images.append(output.image_png)
            for image in images:  # a OpenAI não aceita imagem no resultado da ferramenta
                data = base64.b64encode(image).decode()
                messages.append({"role": "user", "content": [
                    {"type": "text", "text": "Captura de tela pedida pela ferramenta:"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}},
                ]})
        reply.text = "Fiz várias tentativas e não terminei, Du. Me diga como prefere seguir."
        reply.failed = True
        return reply


def make_brain() -> ClaudeBrain | OpenAIBrain:
    if provider_name() == "claude":
        try:
            return ClaudeBrain()
        except ImportError:
            # Pacote do Claude não instalado (falta rodar o preparar_duque.bat): segue com a OpenAI.
            print("[TELEX] pacote 'anthropic' ausente: usando a OpenAI. Rode .\\preparar_duque.bat para usar o Claude.", flush=True)
            if not os.getenv("OPENAI_API_KEY"):
                raise
    return OpenAIBrain()


def explain_error(exc: BaseException) -> str:
    """O erro da IA numa frase que o Du consegue resolver."""
    if isinstance(exc, ImportError):
        missing = getattr(exc, "name", None) or "um pacote"
        return f"Falta instalar o pacote {missing}. Feche o TELEX e rode o preparar_duque.bat."
    name = type(exc).__name__
    text = str(exc).casefold()
    if name == "AuthenticationError" or "api key" in text or "api_key" in text:
        return "A chave da IA não foi aceita. Confira a ANTHROPIC_API_KEY ou a OPENAI_API_KEY."
    if "credit balance" in text or "insufficient_quota" in text or "billing" in text:
        return "A conta da IA está sem créditos."
    if name in {"APIConnectionError", "ConnectError", "ConnectionError", "APITimeoutError"}:
        return "Não consegui me conectar à IA. Confira a internet."
    if name == "RateLimitError":
        return "A IA está limitando os pedidos agora. Tente de novo em um minuto."
    return f"Não consegui falar com a IA agora ({name})."
