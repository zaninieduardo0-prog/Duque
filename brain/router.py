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
    """Roteador heurístico inicial para identificar ações operacionais claras."""

    OPEN_APP_PHRASES = (
        "abrir o navegador", "abrir navegador", "abrir chrome", "abrir o chrome",
        "abrir edge", "abrir o edge", "abrir bloco de notas", "abrir o bloco de notas",
        "abrir notepad", "abrir calculadora", "abrir a calculadora", "abrir whatsapp",
        "abrir o whatsapp", "abra o navegador", "abra navegador", "abra chrome",
        "abra o chrome", "abra edge", "abra o edge", "abra bloco de notas",
        "abra o bloco de notas", "abra notepad", "abra calculadora", "abra a calculadora",
        "abra whatsapp", "abra o whatsapp", "abra o explorador", "abra explorador",
        "abra paint", "inicie o chrome", "inicie o whatsapp", "inicie a calculadora",
    )

    def route(self, text: str) -> Route:
        value = " ".join(text.casefold().strip().split())
        if not value:
            return Route(Intent.UNKNOWN, 0.0, "texto vazio")

        if any(phrase in value for phrase in self.OPEN_APP_PHRASES):
            return Route(Intent.OPEN_APP, 0.95, "pedido explícito para abrir aplicativo")

        if any(x in value for x in (
            "liste os arquivos", "listar os arquivos", "listar arquivos",
            "mostre os arquivos", "mostra os arquivos", "listar a pasta",
            "mostre a pasta", "leia o arquivo", "ler o arquivo", "abra o arquivo",
            "leia arquivo", "ler arquivo", "abra arquivo", "analise o arquivo",
            "analisa o arquivo", "analise arquivo", "analisa arquivo",
            "mostre o conteúdo", "mostre o conteudo", "crie o arquivo",
            "criar o arquivo", "escreva o arquivo", "salve o arquivo",
            "exclua o arquivo", "apague o arquivo", "delete o arquivo",
            "arquivo", "pasta",
        )):
            return Route(Intent.FILE_OPERATION, 0.92, "operação explícita sobre arquivos")

        if any(x in value for x in ("pesquise", "pesquisar", "procure na internet", "busque na internet", "google")):
            return Route(Intent.SEARCH, 0.9, "pedido explícito de pesquisa")

        if any(x in value for x in (
            "crie um código", "criar código", "escreva um código", "programa",
            "programar", "debug", "corrija o código", "implemente",
        )):
            return Route(Intent.CODE, 0.9, "pedido relacionado a programação")

        if any(x in value for x in ("me lembre", "lembrete", "lembrar", "agenda", "agende")):
            return Route(Intent.REMINDER, 0.85, "pedido de lembrete/agendamento")

        if any(x in value for x in (
            "desligue o computador", "desligar o computador", "desligue o pc",
            "desligar o pc", "reinicie o computador", "reiniciar o computador",
            "reinicie o pc", "reiniciar o pc", "aumente o volume", "aumentar o volume",
            "diminua o volume", "diminuir o volume", "mute o computador",
            "mutar o computador", "desative o som", "ative o som",
        )):
            return Route(Intent.SYSTEM, 0.9, "ação explícita de sistema")

        return Route(Intent.CHAT, 0.6, "conversa geral")
