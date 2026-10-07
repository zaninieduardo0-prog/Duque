"""Voz do TELEX: qual voz usar e como ela deve soar.

A mesma escolha vale para a resposta falada do texto (TTS do HUD) e para a
conversa "Hey Jarvis" (Realtime). Só entram vozes que existem nos dois.
"""

from __future__ import annotations

import os
from typing import Any

from memory.memory import Memory, MemoryLayer

# Chave nova: a escolha antiga ("ballad", lenta e teatral) não volta sozinha.
KEY = "voz_telex"
DEFAULT_VOICE = "cedar"

# Vozes disponíveis tanto no TTS quanto no Realtime da OpenAI.
VOICES: dict[str, str] = {
    "cedar": "Masculina, grave e natural (padrão do TELEX).",
    "ballad": "Masculina, suave e refinada, mais lenta e teatral.",
    "ash": "Masculina, clara e firme.",
    "echo": "Masculina, neutra e calma.",
    "verse": "Masculina, expressiva e dinâmica.",
    "alloy": "Neutra, equilibrada.",
    "marin": "Feminina, natural e calorosa.",
    "sage": "Feminina, serena.",
}

SAMPLE = "Às suas ordens, Du. Todos os sistemas estão operando normalmente. Em que posso ajudar?"

# Estilo "J.A.R.V.I.S." para o TTS (gpt-4o-mini-tts aceita instruções de voz).
TTS_INSTRUCTIONS = (
    "Você é o TELEX, assistente pessoal falando português do Brasil com sotaque brasileiro neutro. "
    "Fale como uma pessoa real numa conversa do dia a dia: ritmo de conversa, um pouco acelerado, "
    "frases ligadas umas nas outras, entonação variada e descontraída, confiante e simpático. "
    "Nada de pausas entre as frases, nada de dicção pausada de locutor, nada de tom teatral, solene ou robótico. "
    "Não leia símbolos, emojis nem formatação."
)
def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default  # valor inválido no setx não pode derrubar a importação do TELEX


TTS_SPEED = _env_float("DUQUE_TTS_SPEED", 1.12)

# Mesmo estilo para a conversa por voz (vai nas instruções do Realtime).
VOICE_DELIVERY = (
    "COMO FALAR (muito importante)\n"
    "- Fale como um brasileiro de verdade numa conversa: natural, solto, ritmo normal para rápido, com entonação viva.\n"
    "- Emende as frases. Não faça pausas entre elas, não fale pausado nem silabado, não use tom de locutor, de\n"
    "  mordomo ou de robô. Confiante e simpático, com humor seco de vez em quando.\n"
    "- Comece a falar logo. Respostas curtas, do jeito que alguém responderia em voz alta.\n"
    "- Números, horas e datas do jeito falado (\"duas e meia\", \"vinte e três graus\")."
)


def current_voice(memory: Memory | None) -> str:
    if memory is not None:
        stored = memory.recall(MemoryLayer.PERSONAL, KEY, None)
        if isinstance(stored, str) and stored in VOICES:
            return stored
    env = os.getenv("DUQUE_VOICE", "").strip().casefold()
    return env if env in VOICES else DEFAULT_VOICE


def set_voice(memory: Memory, name: str) -> dict[str, Any]:
    voice = name.strip().casefold()
    if voice not in VOICES:
        options = ", ".join(VOICES)
        return {"success": False, "error": f"Não conheço a voz '{name}'. Opções: {options}."}
    memory.remember(MemoryLayer.PERSONAL, KEY, voice)
    return {
        "message": f"Pronto, agora falo com a voz {voice}. Vale para as respostas e para o 'Hey Jarvis' a partir da próxima conversa.",
        "voice": voice,
    }


def list_voices(memory: Memory | None) -> dict[str, Any]:
    active = current_voice(memory)
    lines = [f"{'→ ' if name == active else ''}{name}: {description}" for name, description in VOICES.items()]
    return {
        "message": "Vozes disponíveis (ouça cada uma no painel MEMÓRIA, seção Voz):\n" + "\n".join(lines),
        "voices": VOICES,
        "active": active,
    }
