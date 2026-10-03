"""Pedidos com várias etapas numa frase só.

"abra o YouTube e toque Coldplay"           → uma etapa: tocar no YouTube
"abra o bloco de notas e escreva um poema"  → uma etapa: escrever no Bloco de Notas
"abra o Spotify, aumente o volume e anote X" → três etapas, uma depois da outra

Primeiro a frase é quebrada nos conectores ("e", "depois", "em seguida", ",")
que vêm antes de um verbo de ação. Depois, etapas que só fazem sentido juntas
são unidas (abrir o app + o que fazer nele). Cada etapa resultante passa pelo
fluxo normal do TELEX (roteador → plano → execução → verificação).
"""

from __future__ import annotations

import re
import unicodedata

# Verbos no imperativo/infinitivo que começam uma nova etapa.
ACTION_VERBS = (
    r"abr[ae]|abrir|abre|toqu?e|toca|tocar|reproduz[ai]?|reproduzir|coloqu?e|coloca|colocar|bota|"
    r"escrev[ae]|escrever|digit[ae]|digitar|pesquis[ae]|pesquisar|procur[ae]|procurar|busqu?e|busca|buscar|"
    r"fech[ae]|fechar|mand[ae]|mandar|envi[ae]|enviar|cri[ae]|criar|aument[ae]|aumentar|diminu[ai]|diminuir|"
    r"paus[ae]|pausar|anot[ae]|anotar|me lembr[ae]|lembr[ae]|salv[ae]|salvar|copi[ae]|copiar|ativ[ae]|ativar|"
    r"deslig[ae]|desligar|pul[ae]|pular|volt[ae]|mostr[ae]|mostrar|le[ia]a?|ler|inici[ae]|iniciar|"
    r"execut[ae]|executar|bloqu[ei][ia]a?|bloquear|silenci[ae]|tir[ae]|ponha|p[oõ]e|faz|fa[cç]a"
)
_CONNECTOR = re.compile(
    rf"\s*(?:,\s*(?:e\s+)?(?:depois\s+|em seguida\s+|ent[aã]o\s+)?|\s+e\s+(?:depois\s+|em seguida\s+|ent[aã]o\s+)?|\s+depois\s+|\s+em seguida\s+)(?=(?:{ACTION_VERBS})\b)",
    flags=re.IGNORECASE,
)
_NAME_PREFIX = re.compile(r"^\s*(?:telex|teles|duque|jarvis)[\s,!.:-]+", flags=re.IGNORECASE)

OPEN = re.compile(r"^(?:por favor[,]?\s+)?(?:abr[ae]|abrir|abre|inici[ae]|iniciar|entr[ae] no|v[aá] (?:para|pro|no))\s+(?:o |a |no |na )?", re.IGNORECASE)
PLAY = re.compile(r"^(?:toqu?e|toca|tocar|reproduz[ai]?|reproduzir|coloqu?e|coloca|colocar|bota|ponha|p[oõ]e|play)\s+(?:a |o |uma |um )?", re.IGNORECASE)
SEARCH = re.compile(r"^(?:pesquis[ae]|pesquisar|procur[ae]|procurar|busqu?e|busca|buscar)\s+(?:por\s+)?", re.IGNORECASE)
WRITE = re.compile(r"^(?:escrev[ae]|escrever|digit[ae]|digitar)[\s:]+", re.IGNORECASE)
# Texto ditado ("escreva: ...", "digite \"...\"") não é quebrado: ele é o conteúdo.
_DICTATION = re.compile(r"\b(?:escrev[ae]|escrever|digit[ae]|digitar)\b[^:\"“]{0,40}[:\"“]", re.IGNORECASE)

NOTEPAD = re.compile(r"\b(?:bloco de notas|notepad)\b", re.IGNORECASE)
SERVICES = ("youtube", "spotify")


def _plain(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def strip_name(text: str) -> str:
    return _NAME_PREFIX.sub("", text.strip())


# Pedidos cujo resto é conteúdo do Du (nota, lembrete, mensagem, rotina,
# Forja, análise do projeto): a frase inteira é uma etapa só.
_WHOLE = re.compile(
    r"^(?:por favor[,]?\s+)?(?:anot[ae]|anotar|lembr[ae]|lembrar|me lembr[ae]|guard[ae]|memoriz[ae]|"
    r"mand[ae]|mandar|envi[ae]|enviar|diga|diz|fal[ae] (?:que|pr[oa])|pergunt[ae]|responda|"
    r"(?:cri[ae]|salv[ae]|nova|edit[ae]|mud[ae]) (?:a |uma )?rotina|agend[ae]|marqu?e|"
    r"melhor[ae]|corrij[ae]|corrig[ei]|implement[ae]|analis[ae]|revis[ae]|investig[ae]|traduz[ai]?|resum[ae])\b"
    r"|\b(?:forja|seu c[oó]digo|rotina \w+:|dizendo)\b"
    # WhatsApp com mensagem: abrir + procurar a pessoa + enviar é uma ação só.
    r"|\b(?:zap|whats\s?app)\b.*\b(?:mand[ae]|envi[ae]|encaminh\w*|escrev[ae]|digit[ae])\b",
    re.IGNORECASE,
)


def split_steps(text: str) -> list[str]:
    """Quebra nos conectores seguidos de verbo de ação ("... e toque ...")."""
    clean = strip_name(text).strip()
    if _WHOLE.search(clean):
        return [clean] if clean else []
    tail = ""
    dictation = _DICTATION.search(clean)
    if dictation:
        # O que vem depois de "escreva:" é texto do Du: não vira etapas.
        head, tail = clean[: dictation.start()], clean[dictation.start():]
        joint = _TRAILING_CONNECTOR.search(head)
        clean = head[: joint.start()] if joint else head
    parts = [part.strip(" ,.;") for part in _CONNECTOR.split(clean)] if clean.strip() else []
    if tail.strip():
        parts.append(tail.strip(" ,;"))
    return [part for part in parts if part]


_TRAILING_CONNECTOR = re.compile(
    r"(?:,\s*(?:e\s+)?(?:depois\s+|em seguida\s+)?|\s+e\s+(?:depois\s+|em seguida\s+)?|\s+depois\s+|\s+em seguida\s+)$",
    flags=re.IGNORECASE,
)


def _opened_service(step: str) -> str | None:
    if not OPEN.match(step):
        return None
    rest = _plain(OPEN.sub("", step, count=1)).strip(" .!")
    for service in SERVICES:
        if rest == service or rest.startswith(service + " "):
            return service
    if NOTEPAD.search(rest) and len(rest.split()) <= 4:
        return "notepad"
    return None


def _without_place(text: str, service: str) -> str:
    """Tira "no YouTube", "lá", "nele" do fim do que tocar/escrever."""
    pattern = rf"\s+(?:no|na|n[oa]s?)\s+{service}\b|\s+(?:l[aá]|nele|nela|ali|a[ií])\s*$"
    if service == "notepad":
        pattern = r"\s+(?:no|na)\s+(?:bloco de notas|notepad)\b|\s+(?:l[aá]|nele|nela|ali|a[ií])\s*$"
    return re.sub(pattern, "", text, flags=re.IGNORECASE).strip(" ,.")


def merge_steps(steps: list[str]) -> list[str]:
    """Une "abrir app" + "o que fazer nele" numa etapa só."""
    merged: list[str] = []
    index = 0
    while index < len(steps):
        step = steps[index]
        nxt = steps[index + 1] if index + 1 < len(steps) else None
        service = _opened_service(step)
        if service and nxt is not None:
            if service in SERVICES and PLAY.match(nxt):
                merged.append(f"toque {_without_place(PLAY.sub('', nxt, count=1), service)} no {service}")
                index += 2
                continue
            if service in SERVICES and SEARCH.match(nxt):
                merged.append(f"pesquise {_without_place(SEARCH.sub('', nxt, count=1), service)} no {service}")
                index += 2
                continue
            if service == "notepad" and WRITE.match(nxt):
                merged.append(f"escreva no bloco de notas: {_without_place(WRITE.sub('', nxt, count=1), 'notepad')}")
                index += 2
                continue
        merged.append(step)
        index += 1
    return merged


def plan_steps(text: str) -> list[str]:
    """Etapas finais de um pedido (uma só quando não há nada para quebrar)."""
    steps = merge_steps(split_steps(text))
    return steps or [text.strip()]
