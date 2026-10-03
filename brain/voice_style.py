"""Voz do Duque: qual voz usar e como ela deve soar.

A mesma escolha vale para a resposta falada do texto (TTS do HUD) e para a
conversa "Hey Jarvis" (Realtime). Só entram vozes que existem nos dois.
"""

from __future__ import annotations

import os
from typing import Any

from memory.memory import Memory, MemoryLayer

KEY = "voz"
DEFAULT_VOICE = "ballad"

# Vozes disponíveis tanto no TTS quanto no Realtime da OpenAI.
VOICES: dict[str, str] = {
    "ballad": "Masculina, suave e refinada. Boa candidata para o estilo Jarvis.",
    "cedar": "Masculina, grave e encorpada (a voz antiga do Duque).",
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
    "Você é o Duque, um assistente de inteligência artificial no estilo J.A.R.V.I.S., falando português do Brasil. "
    "Voz masculina de mordomo britânico sofisticado: calma, segura, elegante e levemente irônica, com dicção precisa. "
    "Fale com fluidez, num ritmo natural e contínuo, ligando as frases como numa conversa, sem pausas longas, "
    "sem arrastar as palavras e sem soar robótico ou teatral. Sorria discretamente na voz. "
    "Não leia símbolos, emojis nem formatação."
)
TTS_SPEED = 1.05

# Mesmo estilo para a conversa por voz (vai nas instruções do Realtime).
VOICE_DELIVERY = (
    "COMO FALAR\n"
    "- Tom de mordomo britânico sofisticado, no estilo J.A.R.V.I.S.: calmo, seguro, elegante, com humor seco.\n"
    "- Fluidez: ritmo natural e contínuo, frases ligadas, sem pausas longas e sem soletrar números.\n"
    "- Comece a responder rápido; prefira frases curtas e bem encadeadas."
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
