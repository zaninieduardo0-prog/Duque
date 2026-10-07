from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from computer.apps import find_app_in_text
from computer.whatsapp_flow import MESSAGE_REQUEST

from .pc_shortcuts import match as pc_shortcut

_PREFIX = r"^(?:(?:duque|telex)[,!]?\s+)?(?:por favor[,]?\s+)?"
# "Telex, você pode abrir o Spotify?" é um pedido: tira a cortesia antes de rotear.
_POLITE = re.compile(
    r"^(?:(?:duque|telex)[\s,!.:-]+)?(?:por favor[,]?\s+)?(?:(?:voc[eê]|vc)\s+)?"
    r"(?:pode|poderia|consegue|conseguiria|daria pra|dá pra|da pra)\s+(?:por favor\s+)?(?:me\s+)?(?=\w)"
)
# "não abra o Chrome", "não quero que abra o WhatsApp": nunca vira ação.
_NEGATED = re.compile(
    r"\b(?:n[aã]o|nunca|jamais)\s+(?:(?:quero|preciso)\s+(?:que\s+)?(?:(?:voc[eê]|vc)\s+)?|precisa\s+(?:mais\s+)?|"
    r"(?:[eé]|eh)\s+(?:pra|para)\s+|vai\s+|mais\s+|me\s+)?"
    r"(?:abr|fech|encerr|mat[ae]|inici|execut|lig[ue]|deslig|reinici|pesquis|procur|busqu|busc[ae]|apag|exclu|delet|"
    r"mand|envi|toqu|toc[ae]|aument|diminu|abaix|lembr|anot|cri[ae]|escrev|digit|copi|bloqu)\w*"
)
# Perguntas sobre COMO fazer algo ("como faço para abrir o Chrome?") são conversa, não ação.
_HOWTO = re.compile(
    r"^(?:(?:duque|telex)[\s,!.:-]+)?(?:e\s+)?(?:"
    r"como\s+(?:(?:[eé]|eh)\s+que\s+)?(?:eu\s+)?(?:fa[çc]o|faz|fazer|fa[çc]a|posso|consigo|se\s+\w+|devo|abro|abrir|fecho|fechar|"
    r"uso|usar|mando|mandar|envio|enviar|pesquiso|pesquisar|crio|criar|apago|apagar|ativo|ativar|desativo|desativar|"
    r"instalo|instalar|desligo|desligar|coloco|colocar|ligo|ligar)\b"
    r"|por\s?qu[eê]\b|pra que serve|para que serve|o que (?:acontece|significa)\b|ser[aá] que\b"
    r"|(?:voc[eê]|vc) sabe (?:como|se|o que|onde|qual)\b|(?:voc[eê]|vc) (?:sabe|consegue) (?:programar|fazer isso)\b"
    r")"
)
_FILE_VERB = re.compile(
    r"\b(?:abr[ae]|abrir|mostr[ae]|mostrar|list[ae]|listar|lei?a|ler|analis[ae]|analisar|cri[ae]|criar|escrev[ae]|escrever|"
    r"salv[ae]|salvar|exclu[ai]|excluir|apagu?e|apaga|apagar|delet[ae]|deletar|procur[ae]|procurar|encontr[ae]|encontrar|"
    r"ach[ae]|achar|localiz[ae]|localizar|busqu?e|busca|buscar)\b"
)
_SYSTEM = re.compile(
    r"\b(?:aument\w*|sob[ea]|subir|diminu\w*|abaix\w*|baix[ae]|baixar)\s+(?:o\s+|um pouco o\s+)?(?:volume|som)\b"
    r"|\bvolume\s+(?:mais\s+)?(?:alto|baixo)\b|\b(?:mut[ae]|mutar|silenci[ae]|silenciar)\b"
    r"|\b(?:desativ[ae]|ativ[ae]|tir[ae]|desliga|deslig[ue]|lig[ue]|liga)\s+o\s+(?:som|mudo)\b"
    r"|\b(?:deslig[ue]|desliga|desligar|reinici[ae]|reiniciar)\s+o\s+(?:computador|pc|notebook)\b"
)
_REMINDER = re.compile(
    r"\bme\s+lembr\w*|\blembrete\b|\bme\s+avis[ae]\s+(?:em|daqui|amanh|[àa]s|quando)|\bagend[ae]\w*\b|\bagendar\b"
    r"|\btimer\b|\bcron[oô]metro\b|\bdaqui a \d"
)
_CODE = re.compile(
    r"\b(?:crie|cria|criar|escreva|escreve|escrever|fa[çc]a|faz|fazer|gere|gera)\s+(?:um|uma|o|a)\s+(?:c[oó]digo|programa|script|fun[çc][aã]o|classe)\b"
    r"|\b(?:corrija|corrige|debugue|depure|depura)\s+(?:o|este|esse|meu)\s+(?:c[oó]digo|programa|script|bug)\b"
    r"|\bcriar c[oó]digo\b|\bimplemente\b"
)
_SEARCH = re.compile(
    r"\b(?:pesquis[ae]|pesquisar|procure na internet|busque na internet|procura na internet|busca na internet)\b"
    r"|\b(?:no|na p[aá]gina do|pelo) google\b|\b(?:abr[ae]|abrir|abre)\s+(?:o\s+)?google\b"
)
# Perguntas de estado sem citar o app ("ele está aberto?") usam o último app citado.
_CONTEXT_CHECK = re.compile(
    r"^(?:e\s+)?(?:(?:ele|ela|isso|o app|o aplicativo|o programa)\s+)?(?:j[aá]\s+)?(?:est[aá]|t[aá]|continua|segue|ficou)\s+"
    r"(?:aberto|aberta|rodando|funcionando|em execu[cç][aã]o|ligado|ligada)\b"
)
_PRONOUN = re.compile(r"\b(?:ele|ela|isso|esse app|esse aplicativo|o mesmo)\b")
OPEN_VERB = re.compile(_PREFIX + r"(?:abr[ae]|abrir|inici[ae]|iniciar|execut[ae]|executar|liga|ligue)\b")
SHORTCUT_PATTERNS = (
    re.compile(r"\b(?:mud[ae]|troc[ae]|us[ae]|coloqu?e|alter[ae]|escolh[ae])\b[^.?!]*\bvoz\b|\b(?:quais|que) vozes\b|\bvozes dispon|\bminhas vozes\b"),
    MESSAGE_REQUEST,
    re.compile(r"\b(?:salv[ae]|guard[ae]|adicion[ae]) (?:o |um |novo )?contato\b|\bmeus contatos\b"),
    re.compile(r"\b(?:cri[ae]|salv[ae]|nova|apagu?e|apaga|exclu[ai]|remov[ae]|rod[ae]|execut[ae]|inici[ae]|ativ[ae]) (?:a |uma )?rotina\b|\bminhas rotinas\b|^(?:duque[,!]?\s+)?(?:ativ[ae] (?:o )?)?modo (?!foco\b)[a-zà-ú]+$"),
    re.compile(r"\bresumo do (?:meu )?dia\b|\bcomo foi (?:o )?meu dia\b|\bo que (?:eu )?fiz hoje\b"),
    re.compile(r"\b(?:o que (?:tem|está|esta|aparece|é isso|e isso) na (?:minha )?tela|l[eê]i?a a tela|olh[ae] (?:a|minha) tela|o que você (?:vê|ve)|o que voce (?:vê|ve)|explica (?:essa|esta|o que tem na) tela|(?:esse|este) erro na tela)\b"),
    re.compile(r"\b(?:modo foco|pomodoro|foco por|(?:sair|sai|encerr[ae]|termin[ae]|desativ[ae]|desliga|para) (?:do |o )?(?:modo )?foco)\b"),
    re.compile(r"\b(?:meus lembretes|minha agenda|o que (?:eu )?tenho (?:agendado|marcado)|cancel(?:a|e|ar) (?:o|os|todos os) lembretes?)\b"),
    re.compile(r"\bno (?:youtube|spotify)\b"),
    re.compile(r"\b(?:escrev[ae]|escrever|digit[ae]|digitar|cri[ae]|criar|fa[çc]a|fazer|componh[ao]|redij[ao]|mont[ae]|ger[ae]|elabor[ae])\b.*\b(?:bloco de notas|notepad)\b"),
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
        value = _POLITE.sub("", value).strip()
        value = re.sub(r"\s*,?\s*por favor\s*([?.!]*)$", r"\1", value)
        if not value:
            return Route(Intent.CHAT, 0.6, "conversa geral")

        # Negação ("não abra o Chrome") e pergunta de "como fazer" nunca disparam ação.
        if _NEGATED.search(value):
            return Route(Intent.CHAT, 0.7, "pedido negado: não executar")
        if _HOWTO.search(value):
            return self._informational(value)

        if pc_shortcut(value) is not None or any(pattern.search(value) for pattern in SHORTCUT_PATTERNS):
            return Route(Intent.SHORTCUT, 0.92, "atalho do dia a dia")

        if any(phrase in value for phrase in self.OPEN_APP_PHRASES):
            return Route(Intent.OPEN_APP, 0.95, "pedido explícito para abrir aplicativo")

        mentions_file = bool(re.search(r"\b(?:arquivos?|pastas?)\b", value))
        if context_app and re.search(r"\b(?:abr[ae]|abrir|inici[ae])\b.*\b(?:novamente|de novo|outra vez)\b", value) and not mentions_file:
            return Route(Intent.OPEN_APP, 0.9, "reabrir o último aplicativo citado")
        if OPEN_VERB.search(value) and not mentions_file and find_app_in_text(value):
            return Route(Intent.OPEN_APP, 0.93, "verbo de abrir + aplicativo conhecido")
        if CLOSE_VERB.search(value) and not mentions_file and find_app_in_text(value):
            return Route(Intent.CLOSE_APP, 0.93, "verbo de fechar + aplicativo conhecido")
        if context_app and CLOSE_VERB.search(value) and _PRONOUN.search(value) and not mentions_file:
            return Route(Intent.CLOSE_APP, 0.88, "fechar o último aplicativo citado")

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

        check_markers = (
            "está aberto", "esta aberto", "está rodando", "esta rodando",
            "está funcionando", "esta funcionando", "está em execução", "esta em execução",
            "rodando?", "aberto?",
        )
        if any(marker in value for marker in check_markers):
            # Precisa citar um app ("o Chrome está aberto?") ou ser só o pronome
            # ("ele está aberto?"); "o mercado está aberto?" não é sobre o último app.
            if find_app_in_text(value) or (context_app and _CONTEXT_CHECK.search(value.strip(" ?!."))):
                return Route(Intent.CHECK_APP, 0.94, "pedido para verificar o estado de um aplicativo")

        if mentions_file and _FILE_VERB.search(value):
            return Route(Intent.FILE_OPERATION, 0.92, "operação explícita sobre arquivos")

        if any(x in value for x in ("abra a página", "abra a pagina", "abre a página", "abre a pagina", "abra o resultado", "abre o resultado", "mostre o resultado")):
            return Route(Intent.OPEN_SEARCH_RESULT, 0.95, "pedido explícito para abrir resultado da pesquisa")

        if _SEARCH.search(value):
            return Route(Intent.SEARCH, 0.9, "pedido explícito de pesquisa")

        if _CODE.search(value):
            return Route(Intent.CODE, 0.9, "pedido relacionado a programação")

        informational = self._informational(value)
        if informational.intent is not Intent.CHAT:
            return informational

        if any(x in value for x in (
            "pausa a música", "pause a música", "pausar a música", "pausa a musica", "pause a musica",
            "próxima música", "proxima musica", "próxima faixa", "proxima faixa", "pula a música", "pula a musica",
            "música anterior", "musica anterior", "volta a música", "volta a musica", "faixa anterior",
            "continua a música", "continua a musica", "solta a música", "solta a musica", "despausa",
        )):
            return Route(Intent.MEDIA, 0.92, "controle de mídia")

        if value.startswith(("anote", "anota", "faça uma nota", "faz uma nota", "lembre que", "lembra que", "guarde que", "guarda que", "memorize que", "memoriza que")) or any(x in value for x in ("minhas notas", "minhas anotações", "minhas anotacoes", "leia as notas", "o que você sabe sobre mim", "o que voce sabe sobre mim", "o que você lembra de mim", "o que voce lembra de mim")):
            return Route(Intent.NOTE, 0.9, "anotação")

        if _REMINDER.search(value):
            return Route(Intent.REMINDER, 0.85, "pedido de lembrete/agendamento")

        if _SYSTEM.search(value):
            return Route(Intent.SYSTEM, 0.9, "ação explícita de sistema")

        return Route(Intent.CHAT, 0.6, "conversa geral")

    @staticmethod
    def _informational(value: str) -> Route:
        """Perguntas que só leem informação (hora, clima, conta): seguras até em "como...?"."""
        if any(x in value for x in ("que horas", "que hora é", "que dia é hoje", "que dia e hoje", "data de hoje", "dia da semana")):
            return Route(Intent.TIME, 0.95, "pergunta de data/hora")
        if any(x in value for x in ("clima", "previsão do tempo", "previsao do tempo", "vai chover", "temperatura lá fora", "temperatura agora", "como está o tempo", "como esta o tempo")):
            return Route(Intent.WEATHER, 0.9, "pergunta sobre o clima")
        if re.match(r"^(?:(?:duque|telex)[,!]?\s+)?(?:quanto é|quanto e|calcule|calcula)\b", value):
            return Route(Intent.CALC, 0.9, "cálculo")
        return Route(Intent.CHAT, 0.6, "conversa geral")
