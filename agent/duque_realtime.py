from __future__ import annotations

import asyncio
import os

from agents import function_tool
from agents.realtime import RealtimeAgent

from brain.persona import voice_instructions
from core.voice_bridge import bridge


@function_tool
async def executar_no_duque(pedido: str) -> str:
    """Executa um pedido usando o cérebro e as ferramentas do TELEX.

    Use para tudo que exige agir: abrir ou fechar aplicativos e pastas, ler e
    procurar arquivos, pesquisar na web, clima, hora, contas, notas, timers e
    lembretes, música e volume, área de transferência, estado do computador,
    YouTube (tocar vídeos), Spotify, mapas, Bloco de Notas, mensagens no
    WhatsApp (acha a pessoa, confere e envia) e melhorias no próprio código (Forja).
    Pedidos com várias etapas ("abra X e faça Y") vão inteiros, numa chamada só.

    Args:
        pedido: o pedido completo do Du, em português, com todos os detalhes e
            com as palavras dele (nomes, pistas como "da Embralan" e o texto exato da mensagem).
    """
    return await asyncio.to_thread(bridge.execute, pedido)


def build_instructions() -> str:
    """Persona + conversa recente (texto e voz) para continuar do mesmo ponto."""
    override = os.getenv("DUQUE_VOICE_INSTRUCTIONS", "").strip()
    if override:
        return override
    return voice_instructions(bridge.context(), bridge.memories())


# Mantido por compatibilidade com quem importava a constante.
DUQUE_REALTIME_INSTRUCTIONS = voice_instructions()


def _build_agent() -> RealtimeAgent:
    """Cria o agente de voz sem depender de estado global do servidor."""
    return RealtimeAgent(
        name="TELEX",
        instructions=DUQUE_REALTIME_INSTRUCTIONS,
        tools=[executar_no_duque],
    )


duque_realtime = _build_agent()


def refresh_instructions() -> None:
    """Chamado no início de cada sessão de voz para trazer o contexto atual."""
    duque_realtime.instructions = build_instructions()
