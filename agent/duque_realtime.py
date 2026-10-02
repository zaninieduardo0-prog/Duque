from __future__ import annotations

import asyncio
import os

from agents import function_tool
from agents.realtime import RealtimeAgent

from brain.persona import voice_instructions
from core.voice_bridge import bridge


@function_tool
async def executar_no_duque(pedido: str) -> str:
    """Executa um pedido usando o cérebro e as ferramentas do Duque.

    Use para tudo que exige agir: abrir ou fechar aplicativos e pastas, ler e
    procurar arquivos, pesquisar na web, clima, hora, contas, notas, timers e
    lembretes, música e volume, área de transferência, estado do computador,
    YouTube, Spotify, mapas e melhorias no próprio código do Duque (Forja).

    Args:
        pedido: o pedido completo do Du, em português, com todos os detalhes.
    """
    return await asyncio.to_thread(bridge.execute, pedido)


def build_instructions() -> str:
    """Persona + conversa recente (texto e voz) para continuar do mesmo ponto."""
    override = os.getenv("DUQUE_VOICE_INSTRUCTIONS", "").strip()
    if override:
        return override
    return voice_instructions(bridge.context())


# Mantido por compatibilidade com quem importava a constante.
DUQUE_REALTIME_INSTRUCTIONS = voice_instructions()


def _build_agent() -> RealtimeAgent:
    """Cria o agente de voz sem depender de estado global do servidor."""
    return RealtimeAgent(
        name="Duque",
        instructions=DUQUE_REALTIME_INSTRUCTIONS,
        tools=[executar_no_duque],
    )


duque_realtime = _build_agent()


def refresh_instructions() -> None:
    """Chamado no início de cada sessão de voz para trazer o contexto atual."""
    duque_realtime.instructions = build_instructions()
