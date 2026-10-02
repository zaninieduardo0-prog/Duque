from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from computer.apps import find_app_in_text

_PREFIX = r"^(?:duque[,!]?\s+)?(?:por favor[,]?\s+)?"
OPEN_VERB = re.compile(_PREFIX + r"(?:abr[ae]|abrir|inici[ae]|iniciar|execut[ae]|executar|liga|ligue)\b")
SHORTCUT_PATTERNS = (
    re.compile(r"\bno (?:youtube|spotify)\b"),
    re.compile(r"\b(?:como (?:chego|chegar|vou)|rota (?:para|até|ate)|mapa (?:de|do|da|para))\b"),
    re.compile(r"\b(?:como (?:está|esta) o (?:computador|pc|notebook)|status do (?:pc|computador|sistema)|uso (?:de|da) (?:cpu|memória|memoria)|quanto de bateria|nível da bateria|nivel da bateria)\b"),
    re.compile(_PREFIX + r"cop(?:ie|ia|iar)\b"),
    re.compile(r"\b(?:área|area) de transferência|\b(?:área|area) de transferencia"),
    re.compile(r"\bbloque(?:ie|ia|ar) (?:a tela|o pc|o computador)\b"),
    re.compile(r"\b(?:meus timers|quais timers|timers ativos|cancel(?:a|e|ar) (?:o|os) timers?)\b"),
)
CLOSE_VERB = re.compile(_PREFIX + r"(?:fech[ae]|fechar|encerr[ae]|encerrar|mat[ae])\b")


class Intent(str, Enum):
    CHAT = "chat"
    OPEN_APP = "open_app"
    CLOSE_APP = "close_app"
    CHECK_APP = "check_app"
    SEARCH = "search"
    OPEN_SEARCH_RESULT = "open_search_result"
    CODE = "code"
    FILE_OPERATION = "file_operation"
    SYSTEM = "system"
    REMINDER = "reminder"
    TIME = "time"
    WEATHER = "weather"
    MEDIA = "media"
    NOTE = "note"
    CALC = "calc"
    SHORTCUT = "shortcut"
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

    def route(self, text: str, context_app: str | None = None) -> Route:
        value = " ".join(text.casefold().strip().split())
        if not value:
            return Route(Intent.UNKNOWN, 0.0, "texto vazio")

        if any(pattern.search(value) for pattern in SHORTCUT_PATTERNS):
            return Route(Intent.SHORTCUT, 0.92, "atalho do dia a dia")

        if any(phrase in value for phrase in self.OPEN_APP_PHRASES):
            return Route(Intent.OPEN_APP, 0.95, "pedido explícito para abrir aplicativo")

        mentions_file = any(word in value for word in ("arquivo", "pasta"))
        if OPEN_VERB.search(value) and not mentions_file and find_app_in_text(value):
            return Route(Intent.OPEN_APP, 0.93, "verbo de abrir + aplicativo conhecido")
        if CLOSE_VERB.search(value) and not mentions_file and find_app_in_text(value):
            return Route(Intent.CLOSE_APP, 0.93, "verbo de fechar + aplicativo conhecido")

        if any(phrase in value for phrase in (
            "feche o chrome", "fechar o chrome", "fecha o chrome",
            "feche o navegador", "fechar o navegador", "fecha o navegador",
            "feche o edge", "fechar o edge", "fecha o edge",
            "feche o whatsapp", "fechar o whatsapp", "fecha o whatsapp",
            "feche o bloco de notas", "fechar o bloco de notas", "fecha o bloco de notas",
            "feche a calculadora", "fechar a calculadora", "fecha a calculadora",
            "feche o paint", "fechar o paint", "fecha o paint",
            "encerre o chrome", "encerra o chrome", "encerre o navegador",
        )):
            return Route(Intent.CLOSE_APP, 0.95, "pedido explícito para fechar aplicativo")

        app_markers = (
            "chrome", "google chrome", "navegador",
            "edge", "microsoft edge",
            "whatsapp", "whatsapp desktop",
            "bloco de notas", "notepad", "calculadora", "calc", "paint",
        )
        check_markers = (
            "está aberto", "esta aberto", "está rodando", "esta rodando",
            "está funcionando", "esta funcionando", "está em execução", "esta em execução",
            "está aberto?", "esta aberto?", "rodando?", "aberto?",
        )
        if (any(app in value for app in app_markers) or context_app) and any(marker in value for marker in check_markers):
            return Route(Intent.CHECK_APP, 0.94, "pedido para verificar o estado de um aplicativo")

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

        if any(x in value for x in ("abra a página", "abra a pagina", "abre a página", "abre a pagina", "abra o resultado", "abre o resultado", "mostre o resultado")):
            return Route(Intent.OPEN_SEARCH_RESULT, 0.95, "pedido explícito para abrir resultado da pesquisa")

        if any(x in value for x in ("pesquise", "pesquisar", "procure na internet", "busque na internet", "google")):
            return Route(Intent.SEARCH, 0.9, "pedido explícito de pesquisa")

        if any(x in value for x in (
            "crie um código", "criar código", "escreva um código", "programa",
            "programar", "debug", "corrija o código", "implemente",
        )):
            return Route(Intent.CODE, 0.9, "pedido relacionado a programação")

        if any(x in value for x in ("que horas", "que hora é", "que dia é hoje", "que dia e hoje", "data de hoje", "dia da semana")):
            return Route(Intent.TIME, 0.95, "pergunta de data/hora")

        if any(x in value for x in ("clima", "previsão do tempo", "previsao do tempo", "vai chover", "temperatura lá fora", "temperatura agora", "como está o tempo", "como esta o tempo")):
            return Route(Intent.WEATHER, 0.9, "pergunta sobre o clima")

        if any(x in value for x in (
            "pausa a música", "pause a música", "pausar a música", "pausa a musica", "pause a musica",
            "próxima música", "proxima musica", "próxima faixa", "proxima faixa", "pula a música", "pula a musica",
            "música anterior", "musica anterior", "volta a música", "volta a musica", "faixa anterior",
            "continua a música", "continua a musica", "solta a música", "solta a musica", "despausa",
        )):
            return Route(Intent.MEDIA, 0.92, "controle de mídia")

        if value.startswith(("anote", "anota", "faça uma nota", "faz uma nota")) or any(x in value for x in ("minhas notas", "minhas anotações", "minhas anotacoes", "leia as notas")):
            return Route(Intent.NOTE, 0.9, "anotação")

        if re.match(r"^(?:duque[,!]?\s+)?(?:quanto é|quanto e|calcule|calcula)\b", value):
            return Route(Intent.CALC, 0.9, "cálculo")

        if any(x in value for x in ("me lembre", "lembrete", "lembrar", "agenda", "agende", "timer", "cronômetro", "cronometro", "me avise em", "me avisa em")):
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
