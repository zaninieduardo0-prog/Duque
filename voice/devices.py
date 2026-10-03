"""Escolha de microfone do Duque.

Microfone de fone Bluetooth em uso faz o Windows trocar o fone para o modo
"chamada" (Hands-Free): o som normal do PC some ou fica péssimo no fone.
Por padrão o Duque evita esses microfones e deixa o fone só para ouvir.
"""

from __future__ import annotations

import os
import re
from typing import Any, Iterable

HANDS_FREE = re.compile(r"hands-?free|\bag audio\b", re.IGNORECASE)


def pick_wake_device(devices: list[str], env: dict[str, str] | None = None) -> tuple[int, str]:
    env = dict(os.environ if env is None else env)
    configured = env.get("DUQUE_WAKE_MIC", "").strip() or env.get("DUQUE_MIC", "").strip()
    if configured:
        return int(configured), "definido em DUQUE_WAKE_MIC/DUQUE_MIC"
    for index, name in enumerate(devices):
        if not HANDS_FREE.search(name):
            return index, "automático (evitando microfone Bluetooth, que silencia o áudio do fone)"
    return (0 if devices else -1), "automático (único disponível)"


def match_input_device(wake_name: str, devices: Iterable[dict[str, Any]]) -> int | None:
    """Índice no sounddevice do mesmo microfone escolhido para a wake word."""
    key = wake_name.casefold()[:24]
    if not key:
        return None
    for index, device in enumerate(devices):
        name = str(device.get("name", "")).casefold()
        if device.get("max_input_channels", 0) > 0 and (key in name or (name and name[:24] in key)) and not HANDS_FREE.search(name):
            return index
    return None
