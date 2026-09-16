from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Intent(str, Enum):
    CHAT = "chat"
    OPEN_APP = "open_app"
    SEARCH = "search"
    CODE = "code"
    FILE_OPERATION = "file_operation"
    SYSTEM = "system"
    REMINDER = "reminder"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class Route:
    intent: Intent
    confidence: float
    reason: str = ""


class IntentRouter:
    """Roteador heurístico inicial; futuramente pode ser substituído pelo LLM."""

    def route(self, text: str) -> Route:
        value = text.casefold().strip()
        if not value:
            return Route(Intent.UNKNOWN, 0.0, "texto vazio")

        if any(x in value for x in ("abrir o navegador", "abrir navegador", "abrir chrome", "abrir edge", "abrir bloco de notas", "abrir notepad")):
            return Route(Intent.OPEN_APP, 0.95, "pedido explícito para abrir aplicativo")
        if any(x in value for x in ("pesquise", "pesquisar", "procure na internet", "busque na internet", "google")):
            return Route(Intent.SEARCH, 0.9, "pedido explícito de pesquisa")
        if any(x in value for x in ("crie um código", "criar código", "escreva um código", "programa", "programar", "debug", "corrija o código", "implemente")):
            return Route(Intent.CODE, 0.9, "pedido relacionado a programação")
        if any(x in value for x in ("arquivo", "pasta", "leia o arquivo", "crie o arquivo", "salve o arquivo")):
            return Route(Intent.FILE_OPERATION, 0.8, "operação de arquivo")
        if any(x in value for x in ("me lembre", "lembrete", "lembrar", "agenda", "agende")):
            return Route(Intent.REMINDER, 0.85, "pedido de lembrete/agendamento")
        if any(x in value for x in ("desligue", "reinicie", "volume", "computador", "sistema")):
            return Route(Intent.SYSTEM, 0.75, "ação de sistema")
        return Route(Intent.CHAT, 0.6, "conversa geral")
