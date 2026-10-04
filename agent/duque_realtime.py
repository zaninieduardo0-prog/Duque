from __future__ import annotations

import asyncio
import os

from agents import function_tool
from agents.realtime import RealtimeAgent

from brain.persona import voice_instructions
from core.voice_bridge import bridge


@function_tool
async def executar_no_duque(pedido: str) -> str:
    """Executa um pedido usando o cérebro e as ferramentas do TELEX (mais de 100).

    Use para TUDO que exige agir no computador ou buscar um dado. Ele sabe, entre outras coisas:
    abrir qualquer app instalado (Menu Iniciar), sites e pastas; listar, focar, minimizar,
    maximizar, encaixar e fechar janelas; abrir páginas das Configurações do Windows (Wi-Fi,
    Bluetooth, som, tela...), brilho, Wi-Fi, estado do PC e captura de tela; criar, ler, renomear,
    compactar e organizar arquivos e pastas; ler o texto de sites, listar links e baixar arquivos;
    pesquisar na web, clima, hora, contas, notas, timers, lembretes e rotinas; música, volume,
    YouTube e Spotify; Bloco de Notas; WhatsApp para PESSOAS E GRUPOS (enviar, deixar escrito e
    ler as últimas mensagens); rascunhos de e-mail (Gmail/Outlook), eventos na agenda do Google e
    compartilhar textos; ver a tela e clicar/digitar quando não há atalho pronto; e melhorias no
    próprio código (Forja).
    Nunca diga ao Du que não existe ferramenta para uma ação no computador: chame esta função e
    deixe o TELEX tentar (se não der, ele explica o motivo real).
    Pedidos com várias etapas ("abra X e faça Y", "crie um poema no bloco de notas e mande no grupo
    Família", "faça um resumo e mande por e-mail para a Ana") vão inteiros, numa chamada só: o TELEX
    passa o resultado de uma etapa para a próxima.
    NUNCA leia em voz alta textos que ele criou (poemas, cartas, mensagens longas): só confirme em uma
    frase o que foi feito, a menos que ele peça para ler.

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
