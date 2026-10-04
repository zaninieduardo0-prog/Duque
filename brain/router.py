from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from computer.apps import KNOWN_APPS, PROCESS_NAMES, normalize_app_name


class Intent(str, Enum):
    CHAT = "chat"
    OPEN_APP = "open_app"
    CLOSE_APP = "close_app"
    CHECK_APP = "check_app"
    SEARCH = "search"
    OPEN_SEARCH_RESULT = "open_search_result"
    FILE_OPERATION = "file_operation"
    UNKNOWN = "unknown"


# Intenções que o planejador heurístico resolve sozinho, sem o modelo.
DETERMINISTIC_INTENTS = frozenset({
    Intent.OPEN_APP.value,
    Intent.CLOSE_APP.value,
    Intent.CHECK_APP.value,
    Intent.SEARCH.value,
    Intent.OPEN_SEARCH_RESULT.value,
    Intent.FILE_OPERATION.value,
})


@dataclass(slots=True)
class Route:
    intent: Intent
    confidence: float


_LEADING = re.compile(r"^(?:(?:ei|ô|oi|olá|ola)\s+)?(?:duque\b[\s,]*)?(?:por\s+favor\b[\s,]*)?")
_TRAILING = re.compile(r"[\s,]*(?:por\s+favor)?[\s.!]*$")
_ARTICLE = r"(?:(?:o|a|os|as)\s+)?(?:(?:aplicativo|app|programa)\s+(?:do\s+|da\s+)?)?"
_OPEN = re.compile(rf"^(?:abr[aei]r?|abre|inicie|iniciar|inicia|execute|executar)\s+{_ARTICLE}(?P<app>.+)$")
_CLOSE = re.compile(rf"^(?:fech[ae]r?|fecha|encerr[ae]r?|encerra|finalize|finalizar)\s+{_ARTICLE}(?P<app>.+)$")
_RESULT = re.compile(
    r"^(?:abr[aei]r?|abre|mostr[ae]r?)\s+(?:o\s+)?"
    r"(?:(?:\d+|primeiro|segundo|terceiro|quarto|quinto|sexto|s[ée]timo|oitavo)º?\s+)?"
    r"resultado(?:\s+(?:n[úu]mero\s+)?\d+)?$"
)
_SEARCH = re.compile(
    r"^(?:pesquis[ea]r?|busque|buscar|busca|procure|procurar|procura)\s+"
    r"(?:(?:na\s+internet|no\s+google|na\s+web)\s+)?(?:(?:sobre|por)\s+)?(?P<query>.+)$"
)
_FILE = re.compile(
    r"^(?:(?:liste|listar|lista|mostre|mostra)\s+(?:os\s+)?arquivos"
    r"|(?:leia|ler|l[êe])\s+o\s+arquivo\s+\S"
    r"|mostr[ae]\s+o\s+conte[úu]do\s+(?:do\s+arquivo\s+|de\s+)\S"
    r"|(?:crie|criar|escreva|salve)\s+o\s+arquivo\s+\S.*\scom\s+conte[úu]do\s"
    r"|(?:apague|delete|exclua)\s+o\s+arquivo\s+\S)"
)
_CHECK = re.compile(r"\b(?:est[áa]|t[áa])\s+(?:aberto|aberta|rodando|funcionando|em\s+execu[çc][ãa]o)\b")
_PRONOUN = re.compile(r"\b(?:ele|ela|isso)\b")
_QUESTION_START = re.compile(r"^(?:como|qual|quais|quando|onde|por\s*que|porque|o\s+que|quem|será|sera|posso|pode|você|voce)\b")


def normalize(text: str) -> str:
    value = " ".join(text.casefold().strip().split())
    value = _LEADING.sub("", value, count=1)
    return _TRAILING.sub("", value, count=1).strip()


def _known(app: str, names: Mapping[str, object]) -> bool:
    return normalize_app_name(app) in names


class IntentRouter:
    """Roteador heurístico: só reconhece comandos claros e completos.

    Qualquer frase ambígua (negação, pergunta, pedido composto, app
    desconhecido) vira conversa e fica para o modelo decidir, em vez de virar
    uma ação errada.
    """

    def route(self, text: str, context_app: str | None = None) -> Route:
        value = normalize(text)
        if not value:
            return Route(Intent.UNKNOWN, 0.0)

        is_question = "?" in value or bool(_QUESTION_START.match(value))
        negated = value.startswith(("não ", "nao ", "nunca "))

        if _CHECK.search(value):
            mentions_app = any(re.search(rf"\b{re.escape(app)}\b", value) for app in PROCESS_NAMES)
            if mentions_app or (context_app and _PRONOUN.search(value)):
                return Route(Intent.CHECK_APP, 0.94)

        if is_question or negated:
            return Route(Intent.CHAT, 0.6)

        command = value.rstrip("?")
        if _RESULT.match(command):
            return Route(Intent.OPEN_SEARCH_RESULT, 0.95)

        # Pedidos compostos ("abra o chrome e pesquise...") ficam para o modelo.
        compound = re.search(r"\s(?:e|depois|então|entao)\s", command) is not None

        match = _OPEN.match(command)
        if match and not compound and _known(match.group("app"), KNOWN_APPS):
            return Route(Intent.OPEN_APP, 0.95)

        match = _CLOSE.match(command)
        if match and not compound and _known(match.group("app"), PROCESS_NAMES):
            return Route(Intent.CLOSE_APP, 0.95)

        if _SEARCH.match(command) and not compound:
            return Route(Intent.SEARCH, 0.9)

        if _FILE.match(command):
            return Route(Intent.FILE_OPERATION, 0.92)

        return Route(Intent.CHAT, 0.6)
