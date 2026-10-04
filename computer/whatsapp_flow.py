"""Mandar mensagem no WhatsApp Desktop de ponta a ponta, com conferência.

Pedido típico do Du: "abra o WhatsApp, procure pelo Otávio que trabalha
comigo na Embralan e encaminhe a mensagem X".

Fluxo:
1. Contato salvo (com telefone) → abre a conversa direto pelo link do WhatsApp.
   Senão → abre o app, busca o nome (Ctrl+F) e escolhe o resultado; com uma
   pista ("da Embralan") a visão da tela ajuda a escolher o resultado certo.
2. Confere pela tela que a conversa aberta é mesmo dessa pessoa. Se não for,
   NÃO escreve nada e avisa.
3. Cola o texto e, se o Du pediu para enviar, aperta Enter e confere que a
   mensagem apareceu na conversa.

Sem a visão da tela (sem chave da OpenAI), o TELEX não tem como conferir:
deixa a mensagem escrita e o Du aperta Enter.
"""

from __future__ import annotations

import re
import time
import unicodedata
import urllib.parse
from dataclasses import dataclass
from typing import Any, Callable


def _plain(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", (text or "").casefold())
    no_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", no_accents))


@dataclass(slots=True, frozen=True)
class WhatsAppRequest:
    contact: str
    hint: str
    text: str
    send: bool
    profile: str = ""  # perfil do Chrome (WhatsApp Web); vazio = app do WhatsApp
    group: bool = False  # "grupo Teste": contact traz só o nome do grupo (grupos não têm telefone)


WEB_URL = "https://web.whatsapp.com/"
_PROFILE = re.compile(
    r"(?:,\s*)?\s*(?:(?:no|pelo|usando o)\s+whats\s?app\s+web\s+)?(?:n[oa]|pel[oa]|d[oa]|usando o)\s+(?:perfil|conta)\s+(?:d[oa]\s+|de\s+)?"
    r"(?P<profile>[\wÀ-ú@.\-]+(?:\s+(?!(?:voc[eê]|tu|mand|envi|encaminh|escrev|procur|busc|abr|para|pro|pra|e)\b)[\wÀ-ú@.\-]+)?)",
    re.IGNORECASE,
)


CURRENT_PROFILE = "atual"
_CURRENT = re.compile(
    r"perfil (?:em )?que (?:eu )?(?:estou|to|tô|uso)(?: (?:agora|usando|no momento|aberto))*|perfil atual|perfil aberto|"
    r"(?:esse|este|nesse|neste|desse|deste) perfil|perfil (?:desse|deste|aqui)",
    re.IGNORECASE,
)


def split_profile(text: str) -> tuple[str, str]:
    """("no perfil Embralan, mande ... ") → ("Embralan", "mande ...")."""
    def current(match: re.Match[str]) -> str:
        # "desse perfil" → "do perfil atual"; "perfil em que estou" → "perfil atual"
        return ("do perfil " if not match.group().casefold().startswith("perfil") else "perfil ") + CURRENT_PROFILE

    text = _CURRENT.sub(current, text)
    match = _PROFILE.search(text)
    if not match:
        return "", text
    rest = (text[: match.start()] + " " + text[match.end():]).strip(" ,")
    return match.group("profile").strip(), re.sub(r"\s{2,}", " ", rest)


_APP = r"(?:whats\s?app|whats|zap(?:zap)?)"  # como o Du chama o aplicativo
_SEND_VERBS = r"encaminh\w*|mand[ae]\w*|envi[ae]\w*|diga|diz|fal[ae]|avis[ae]\w*|pergunt[ae]\w*"
_WRITE_VERBS = r"escrev\w*|digit\w*|prepar\w*|deix[ae] escrit\w*"
_VERBS = rf"{_SEND_VERBS}|{_WRITE_VERBS}"
_MSG_NOUN = r"(?:uma |um |a )?(?:mensagem|msg|recado|zap|whats\s?app|whats)?"
_INTRO = (
    r"(?:dizendo(?: que)?|falando(?: que)?|avisando(?: que)?|informando(?: que)?|perguntando(?: se)?|"
    r"lembrando(?: que)?|contando(?: que)?|com o texto|escrito|que)"
)
_GREETINGS = r"(?:oi|ol[aá]|bom dia|boa tarde|boa noite|abra[cç]o|beijo|parab[eé]ns|feliz anivers[aá]rio)"

# Qualquer jeito de pedir uma mensagem (o roteador e o planejador usam este mesmo regex).
MESSAGE_REQUEST = re.compile(
    rf"\b(?:mand[ae]\w*|envi[ae]\w*|encaminh\w*|escrev[ae]|digit[ae]|avis[ae]\w*|pergunt[ae]\w*|respond\w*|cham[ae]|fal[ae]|diga|diz)\b"
    rf"[^.?!]*\b(?:mensagem|msg|recado|{_APP})\b"
    rf"|\b{_APP}\b.*\b(?:mand[ae]\w*|envi[ae]\w*|encaminh\w*|escrev[ae]|digit[ae]|avis[ae]\w*|respond\w*|diga|diz|fal[ae])\b"
    rf"|\b(?:mand[ae]|envi[ae])\s+(?:um |uma )?{_GREETINGS}\s+(?:para|pro|pra)\b"
    # "manda no grupo Teste dizendo oi": grupo já diz que é conversa de mensagens.
    rf"|\b(?:mand[ae]\w*|envi[ae]\w*|escrev[ae]|avis[ae]\w*|fal[ae])\s+(?:\w+\s+){{0,2}}(?:n[oa]|pr[oa]|para|pra)\s+(?:o\s+)?grupo\s+\w",
    re.IGNORECASE,
)

_known_names: Callable[[], list[str]] = lambda: []  # noqa: E731


def set_known_names(provider: Callable[[], list[str]]) -> None:
    """Nomes da agenda de contatos: ajudam a separar "pra Maria Clara oi tudo bem" em nome e texto."""
    global _known_names
    _known_names = provider

# "... procure pelo Otávio que trabalha comigo na Embralan, e encaminhe a mensagem X"
_SEARCH_FORM = re.compile(
    r"(?:procur\w*|busc\w*|ach[ae]\w*|encontr\w*|localiz\w*|abr\w* (?:a )?conversa (?:com|d[oa]))\s+"
    r"(?:(?:pel[oa]|por|o|a)\s+)?(?P<who>.+?)\s*(?:,\s*|\s+)(?:e\s+)?(?:depois\s+|ent[aã]o\s+|a[ií]\s+)?"
    rf"(?P<verb>{_VERBS})[\s:]+(?P<rest>.+)$",
    re.IGNORECASE | re.DOTALL,
)
# "mande (no WhatsApp) para o Otávio: X" / "manda uma mensagem pro Otávio dizendo que X"
_TO_FORM = re.compile(
    rf"(?P<verb>{_VERBS})\s+{_MSG_NOUN}\s*(?:(?:no|pelo) {_APP}\s+)?"
    rf"(?:para|pro|pra|ao|à)\s+(?:o |a )?(?P<who>.+?)(?:\s+(?:no|pelo) {_APP})?"
    rf"(?:\s+{_INTRO}\s+|\s*:\s*)(?P<rest>.+)$",
    re.IGNORECASE | re.DOTALL,
)
# "chama o João no whatsapp e fala que cheguei" / "responde a Ana dizendo ok" / "avisa o Pedro que vou atrasar"
_CALL_FORM = re.compile(
    rf"(?:cham[ae]|avis[ae]|responde\w*|pergunt[ae]|fal[ae] com)\s+(?:para |pro |pra )?(?:o |a )?(?P<who>.+?)"
    rf"(?:\s+(?:no|pelo) {_APP})?\s*(?:,\s*|\s+)(?:e\s+)?"
    rf"(?:(?:diga|diz|fala|fale|manda|mande|avisa|pergunta|responde)\s+(?:que\s+|se\s+|pra ele\s+|pra ela\s+)?|{_INTRO}\s+)(?P<rest>.+)$",
    re.IGNORECASE | re.DOTALL,
)
# "manda um oi pra Maria (no zap)"
_GREETING_FORM = re.compile(
    rf"(?:{_SEND_VERBS})\s+(?:um |uma )?(?P<rest>{_GREETINGS})\s*(?:(?:no|pelo) {_APP}\s+)?"
    rf"(?:para|pro|pra|ao|à)\s+(?:o |a )?(?P<who>.+?)(?:\s+(?:no|pelo) {_APP})?\s*$",
    re.IGNORECASE,
)
# "envia no zap pra Maria oi tudo bem": sem separador entre o nome e o texto.
_NO_SEP_FORM = re.compile(
    rf"(?:{_VERBS})\s+{_MSG_NOUN}\s*(?:(?:no|pelo) {_APP}\s+)?(?:para|pro|pra|ao|à)\s+(?:o |a )?(?P<tail>.+)$",
    re.IGNORECASE | re.DOTALL,
)
_MESSAGE_STARTERS = re.compile(
    r"^(?:oi|ol[aá]|bom dia|boa tarde|boa noite|tudo bem|tudo bom|e a[ií]|beleza|valeu|obrigad[oa]|feliz|parab[eé]ns|"
    r"estou|to|t[ôo]|vou|j[aá]|preciso|cheguei|quando|onde|como|voc[eê]|vc|pode|podemos|vamos|n[aã]o|sim)\b",
    re.IGNORECASE,
)


_CARRY_OBJECT = (
    r"(?:(?:isso|ele|ela|esse|essa|o poema|a poesia|o texto|a carta|a mensagem|o que (?:voc[eê] )?(?:escreveu|criou|fez)|tudo|o arquivo)\s+)?"
)
# "mande pro contato Maria no whatsapp web, sem ler pra mim" — o texto vem da etapa anterior.
_DELIVERY_FORM = re.compile(
    rf"^(?:por favor[,]?\s+)?(?:{_SEND_VERBS})\s+{_CARRY_OBJECT}(?:(?:no|pelo) {_APP}(?:\s+web)?\s+)?"
    rf"(?:para|pro|pra|ao|à)\s+(?:o |a )?(?:contato |cliente |amig[oa] )?(?P<who>.+?)"
    rf"(?:\s+(?:no|pelo) {_APP}(?:\s+web)?)?(?:\s*[,.]?\s*(?:sem|n[aã]o)\b.*)?\s*$",
    re.IGNORECASE | re.DOTALL,
)


def parse_delivery(text: str) -> WhatsAppRequest | None:
    """Pedido de ENTREGAR algo já pronto a um contato (o texto fica vazio; quem chama preenche)."""
    profile, body = split_profile(text)
    body = re.sub(r"^\s*(?:telex[\s,!.:-]+)?", "", body.strip(), flags=re.IGNORECASE).strip(" .")
    match = _DELIVERY_FORM.match(_normalize_groups(body))
    if not match:
        return None
    who = match.group("who")
    if re.search(r"\b(?:dizendo|falando|avisando|perguntando|informando|lembrando|contando)\b|:", who, flags=re.IGNORECASE):
        return None  # traz o texto da mensagem: não é uma entrega pura
    contact, hint, group = _recipient(who)
    if not contact:
        return None
    if not profile and re.search(r"\bweb\b", text, flags=re.IGNORECASE):
        profile = CURRENT_PROFILE  # "whatsapp web" sem perfil: o Chrome que ele já está usando
    return WhatsAppRequest(contact, hint, "", True, profile, group)


def _name_and_message(tail: str) -> tuple[str, str] | None:
    """Separa "Maria Clara oi tudo bem" em ("Maria Clara", "oi tudo bem"), pela agenda ou por um começo de frase."""
    tail = re.sub(r"\s+(?:no|pelo) " + _APP + r"\s+", " ", " " + tail.strip() + " ", flags=re.IGNORECASE).strip()
    wanted = _plain(tail)
    try:
        known = [n for n in _known_names() if n.strip()]
    except Exception:  # agenda indisponível (banco fechado...): segue só com o começo de frase
        known = []
    for name in sorted(known, key=len, reverse=True):
        plain_name = _plain(name)
        if plain_name and wanted.startswith(plain_name + " "):
            count = len(plain_name.split())
            return name, " ".join(tail.split()[count:])
    words = tail.split()
    for cut in range(1, min(4, len(words))):
        if _MESSAGE_STARTERS.match(" ".join(words[cut:])):
            return " ".join(words[:cut]), " ".join(words[cut:])
    return None


def _clean_text(rest: str) -> str:
    text = rest.strip()
    text = re.sub(r"^(?:a |uma )?(?:seguinte )?(?:mensagem|msg|recado|texto)\b\s*(?:no whats\s?app|no zap)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^(?:dizendo|falando|escrito|com o texto)(?: que)?\s+", "", text, flags=re.IGNORECASE)
    text = text.lstrip(":,- ").strip()
    if len(text) >= 2 and text[0] in "\"“'" and text[-1] in "\"”'":
        text = text[1:-1].strip()
    return text


_ROLES = re.compile(r"^(?:o |a )?(cliente|contato|colega|amig[oa]|chefe|fornecedor[a]?|s[r]a?\.?|senhor[a]?|dona|seu)\s+", re.IGNORECASE)


def _split_who(who: str) -> tuple[str, str]:
    """"Otávio que trabalha comigo na Embralan" → ("Otávio", "trabalha comigo na Embralan")."""
    who = re.sub(rf"\s+(?:no|pelo) {_APP}(?:\s+web)?\b", "", who.strip(" ,.:"), flags=re.IGNORECASE)
    role = _ROLES.match(who)
    if role:
        name, hint = _split_who(who[role.end():])
        return name, (role.group(1) + (" " + hint if hint else "")).strip()
    for pattern in (r"\s*,?\s+que\s+", r"\s*,\s*", r"\s+(?:l[aá] )?(?:da|do)\s+"):
        parts = re.split(pattern, who, maxsplit=1)
        if len(parts) == 2 and parts[0].strip():
            return parts[0].strip(), parts[1].strip(" ,.")
    return who, ""


# "o grupo Teste", "conversa do grupo Família", "a conversa Teste" → nome sem o rótulo.
_GROUP_PREFIX = re.compile(
    r"^(?:(?:o|a|meu|minha|nosso|nossa)\s+)?(?:(?P<group>(?:conversa\s+d[oa]\s+)?grupo)|conversa)(?:\s+d[oa](?=\s))?\s*[:\s]\s*",
    re.IGNORECASE,
)
# "no grupo X" / "na conversa X" / "em grupo X" → "para o grupo X" (as formas de pedido usam "para").
_GROUP_PREPOSITION = re.compile(r"\b(?:n[oa]|em|dentro d[oa])\s+(?:o\s+|a\s+)?(?=(?:grupo|conversa)\s)", re.IGNORECASE)
# "do zap" / "do whatsapp" no fim do destinatário = "no zap".
_OF_APP = re.compile(rf"\s+(?:d[oa])\s+{_APP}(?=\s+web\b|\s*[,.:]|\s+(?:{_INTRO})\b|\s*$|\s+(?:sem|n[aã]o)\b)", re.IGNORECASE)


def _normalize_groups(body: str) -> str:
    body = _GROUP_PREPOSITION.sub("para a ", body)
    body = re.sub(r"\bpara a (?=grupo\s)", "para o ", body, flags=re.IGNORECASE)
    return _OF_APP.sub(" no whatsapp", body)


def split_group(name: str) -> tuple[str, bool]:
    """"grupo Teste" → ("Teste", True); "conversa Ana" → ("Ana", False); "Ana" → ("Ana", False)."""
    name = (name or "").strip()
    match = _GROUP_PREFIX.match(name + " ")
    if not match:
        return name, False
    bare = name[match.end():].strip() if match.end() <= len(name) else ""
    bare = bare.strip(" ,.:").strip("\"“”'").strip()
    if not bare:
        return name, False  # só "grupo": não há nome para tirar o rótulo
    return bare, bool(match.group("group"))


def _recipient(who: str) -> tuple[str, str, bool]:
    """Contato, pista e se é grupo. Grupos não passam por "da/do" (é parte do nome: "Família do Zé")."""
    cleaned = re.sub(rf"\s+(?:no|pelo|d[oa]) {_APP}(?:\s+web)?\b", "", who.strip(" ,.:"), flags=re.IGNORECASE)
    name, group = split_group(cleaned)
    if group:
        parts = re.split(r"\s*,?\s+que\s+|\s*,\s*", name, maxsplit=1)
        hint = parts[1].strip(" ,.") if len(parts) == 2 and parts[0].strip() else ""
        return (parts[0].strip() if hint else name), hint, True
    contact, hint = _split_who(name)
    contact = re.sub(r"^(?:meu|minha)\s+", "", contact, flags=re.IGNORECASE)  # "minha mãe" → "mãe" (como está salvo)
    return contact, hint, False


def parse_request(text: str) -> WhatsAppRequest | None:
    """Contato, pista, texto e se é para enviar. None se a frase não é um envio de mensagem."""
    profile, text = split_profile(text)
    body = re.sub(r"^\s*(?:telex[\s,!.:-]+)?", "", text.strip(), flags=re.IGNORECASE)
    body = re.sub(r"\s+(?:no|pelo) whats\s?app web\b", " no whatsapp", body, flags=re.IGNORECASE)
    body = re.sub(r"^(?:por favor[,]?\s+)?(?:abr[ae]|abrir|abre)\s+o\s+(?:whats\s?app|zap)\s*(?:,\s*|\s+e\s+)?", "", body, flags=re.IGNORECASE)
    body = _normalize_groups(body)
    for form in (_SEARCH_FORM, _TO_FORM, _CALL_FORM, _GREETING_FORM, _NO_SEP_FORM):
        match = form.search(body)
        if not match:
            continue
        groups = match.groupdict()
        if groups.get("tail") is not None:
            split = _name_and_message(groups["tail"])
            if split is None:
                continue
            who, rest = split
        else:
            who, rest = groups["who"], groups["rest"]
        contact, hint, group = _recipient(who)
        message = _clean_text(rest)
        if not contact or not message:
            continue
        send = not re.fullmatch(_WRITE_VERBS, groups.get("verb") or "", flags=re.IGNORECASE)
        return WhatsAppRequest(contact, hint, message, send, profile, group)
    return None


# Vários envios numa frase ("no perfil A mande para X ... e no perfil B mande para Y ... ambos dizendo Z").
_JOB_SPLIT = re.compile(r"(?:[.;]\s*|,?\s+)(?:e\s+)?(?:em seguida|depois|tamb[eé]m)?\s*,?\s*(?=(?:n[oa]|pel[oa])\s+(?:perfil|conta)\b)", re.IGNORECASE)
_SHARED_TEXT = re.compile(r"[.,]?\s*(?:e\s+)?(?:ambos|ambas|os dois|as duas|todos|todas|nos dois|nas duas)\b[^:]*?(?:dizendo|falando|com o texto|com a mensagem)(?: que)?\s*:?\s*(?P<text>.+)$", re.IGNORECASE | re.DOTALL)


def parse_many(text: str) -> list[WhatsAppRequest]:
    """Lista de envios (um por perfil). Vazia se não entendeu."""
    shared = ""
    body = text.strip()
    match = _SHARED_TEXT.search(body)
    if match:
        shared = match.group("text").strip().strip("\"“”'").strip()
        body = body[: match.start()].strip()
    parts = [part.strip(" ,.") for part in _JOB_SPLIT.split(body) if part and part.strip(" ,.")]
    jobs: list[WhatsAppRequest] = []
    for part in parts:
        candidate = part
        if shared and not re.search(r"(?:dizendo|falando|:|mensagem\s+\S)", part, re.IGNORECASE):
            candidate = f"{part}: {shared}"
        request = parse_request(candidate)
        if request is None and shared:
            profile, rest = split_profile(part)
            who = re.search(r"(?:para|pro|pra|ao|à)\s+(?:o |a )?(?P<who>.+?)\s*$", _normalize_groups(rest), re.IGNORECASE)
            if who:
                contact, hint, group = _recipient(who.group("who"))
                request = WhatsAppRequest(contact, hint, shared, True, profile, group)
        if request is not None:
            jobs.append(request)
    return jobs


def _answer_number(answer: str | None) -> int | None:
    match = re.search(r"\d+", answer or "")
    return int(match.group()) if match else None


class WhatsAppDesktop:
    def __init__(
        self,
        *,
        open_app: Callable[[str], Any],
        open_target: Callable[[str], Any],
        keys: Any,
        ask_screen: Callable[[str], str | None] | None,
        phone_of: Callable[[str], str | None] = lambda _name: None,
        wait_window: Callable[[str, float], bool] = lambda _f, _t: True,
        focus: Callable[[str], bool] = lambda _f: True,
        sleep: Callable[[float], None] = time.sleep,
        without_vision: Callable[[str, str], dict[str, Any]] | None = None,
        find_profile: Callable[[str], dict[str, str] | None] = lambda _p: None,
        open_in_profile: Callable[[str, str], Any] = lambda _d, _u: None,
        open_current: Callable[[str], bool] = lambda _u: False,
        profile_names: Callable[[], list[str]] = lambda: [],
    ) -> None:
        self.open_app = open_app
        self.open_target = open_target
        self.keys = keys
        self.ask_screen = ask_screen
        self.phone_of = phone_of
        self.wait_window = wait_window
        self.focus = focus
        self.sleep = sleep
        # Sem visão da tela não há como conferir a conversa: só deixa a mensagem pronta.
        self.without_vision = without_vision
        self.find_profile = find_profile
        self.open_in_profile = open_in_profile
        self.open_current = open_current
        self.profile_names = profile_names

    # conferências pela tela ---------------------------------------------------
    def _ask(self, question: str) -> str | None:
        if self.ask_screen is None:
            return None
        try:
            return self.ask_screen(question)
        except Exception:
            return None

    def _open_chat_name(self) -> str | None:
        return self._ask(
            "Olhe a janela do WhatsApp. Qual é o nome do contato ou grupo no topo da conversa aberta? "
            "Responda só o nome, exatamente como aparece. Se nenhuma conversa estiver aberta, responda NENHUMA."
        )

    @staticmethod
    def _same_person(contact: str, seen: str | None, group: bool = False) -> bool | None:
        if seen is None:
            return None
        wanted = _plain(contact).split()
        shown = _plain(seen)
        if not wanted or "nenhuma" in shown.split():
            return False
        if group:
            # Grupo: o topo mostra o nome do grupo (às vezes com emoji ou "Grupo"); vale o nome inteiro ou a 1ª palavra.
            return " ".join(wanted) in shown or wanted[0] in shown.split()
        return wanted[0] in shown.split()

    # fluxo --------------------------------------------------------------------
    def whatsapp_send(
        self, contact: str, text: str, hint: str = "", send: bool = True, profile: str = "", group: bool = False,
    ) -> dict[str, Any]:
        contact, text, profile = (contact or "").strip(), (text or "").strip(), (profile or "").strip()
        contact, named_group = split_group(contact)  # o modelo às vezes manda contact="grupo Teste"
        group = bool(group) or named_group
        if not contact or not text:
            return {"success": False, "error": "Preciso do contato (pessoa ou grupo) e do texto da mensagem."}
        if profile:
            return self._send_web(contact, text, hint, send, profile, group)
        if self.ask_screen is None and self.without_vision is not None:
            result = self.without_vision(contact, text)
            if group and isinstance(result, dict) and result.get("success") is not False:
                # A agenda só tem pessoas: o aviso "não tenho o número" não serve para grupo.
                result = {**result, "message": f"Abri o WhatsApp com a mensagem pronta. É só escolher o grupo {contact} e apertar Enter.", "group": True}
            return result
        phone = None if group else self.phone_of(contact)  # grupo não tem telefone: sempre pela busca
        failure = self._open_desktop_chat(contact, hint, phone, text, group)
        if failure is not None:
            return failure
        return self._verify_type_send(contact, text, send, typed=bool(phone), where="WhatsApp", group=group)

    def _open_desktop_chat(self, contact: str, hint: str, phone: str | None, text: str | None, group: bool) -> dict[str, Any] | None:
        """Abre a conversa no app (link com telefone ou busca). Devolve o erro, ou None se abriu."""
        web = False
        if phone:
            query = {"phone": phone} if text is None else {"phone": phone, "text": text}
            url = "whatsapp://send?" + urllib.parse.urlencode(query, quote_via=urllib.parse.quote)
            self.open_target(url)
        else:
            try:
                opened = self.open_app("whatsapp")
            except Exception as exc:
                return {"success": False, "error": f"Não consegui abrir o WhatsApp: {exc}"}
            # Sem o app instalado, open_app abre o WhatsApp Web no Chrome: lá o
            # Ctrl+F é a busca da PÁGINA, não a de conversas.
            web = isinstance(opened, dict) and bool(opened.get("web"))
        if not self.wait_window("WhatsApp", 20.0):
            return {"success": False, "error": "O WhatsApp não abriu a tempo."}
        if not self.focus("WhatsApp"):
            # Sem foco, as teclas (busca, texto, Enter) iriam para outra janela.
            return {"success": False, "error": "Abri o WhatsApp, mas não consegui trazer a janela para a frente. Não escrevi nada."}
        self.sleep(2.0)
        if not phone:
            self.keys.press("esc")
            if web:
                self.keys.hotkey("ctrl", "alt", "/")  # busca do WhatsApp Web
            else:
                self.keys.hotkey("ctrl", "f")
            self._search_and_open(contact, hint, group)
        return None

    def whatsapp_read(self, contact: str, count: int = 5, group: bool = False, hint: str = "", profile: str = "") -> dict[str, Any]:
        """Abre a conversa (pessoa ou grupo), confere pela tela e lê as últimas mensagens. Não escreve nada na conversa."""
        contact, profile = (contact or "").strip(), (profile or "").strip()
        contact, named_group = split_group(contact)
        group = bool(group) or named_group
        if not contact:
            return {"success": False, "error": "De qual conversa (pessoa ou grupo) eu leio as mensagens?"}
        if self.ask_screen is None:
            return {"success": False, "error": "Sem a visão da tela (chave da OpenAI) não consigo ler as mensagens do WhatsApp."}
        try:
            count = max(1, min(20, int(count)))
        except (TypeError, ValueError):
            count = 5
        if profile:
            stop, where = self._open_web_chat(contact, hint, profile, group)
            if stop is not None:
                return stop if stop.get("success") is False else {"success": False, "error": str(stop.get("message"))}
        else:
            where = "WhatsApp"
            phone = None if group else self.phone_of(contact)
            failure = self._open_desktop_chat(contact, hint, phone, None, group)
            if failure is not None:
                return failure
        seen = self._open_chat_name()
        same = self._same_person(contact, seen, group)
        if same is not True:
            if same is False:
                self.keys.press("esc")
            return {
                "success": False,
                "error": f"Não achei a conversa certa: procurei '{contact}' e abriu '{seen}'." if same is False
                else "Abri o WhatsApp, mas não consegui conferir a conversa pela tela.",
            }
        answer = self._ask(
            f"Na conversa aberta do WhatsApp ('{seen}'), transcreva as últimas {count} mensagens visíveis, da mais antiga "
            "para a mais recente, uma por linha, no formato 'Remetente: texto'. Use 'Eu' para as minhas (balões à direita); "
            "em grupo, use o nome que aparece acima do balão. Para foto, áudio ou figurinha escreva [foto], [áudio] ou "
            "[figurinha]. Não invente nada. Se não houver mensagens visíveis, responda NENHUMA."
        )
        if answer is None:
            return {"success": False, "error": f"Abri a conversa com {seen}, mas não consegui ler a tela."}
        lines = [line.strip(" -•\t") for line in answer.splitlines() if line.strip(" -•\t")]
        if not lines or _plain(lines[0]) == "nenhuma":
            return {"message": f"Não vi mensagens na conversa com {seen}.", "messages": [], "chat": seen, "group": group}
        lines = lines[-count:]
        return {
            "message": f"Últimas mensagens de {seen} ({where}):\n" + "\n".join(lines),
            "messages": lines, "chat": seen, "group": group,
        }

    def _search_and_open(self, contact: str, hint: str, group: bool = False) -> None:
        self.sleep(0.6)
        self.keys.type_text(contact)
        self.sleep(2.0)
        position = 1
        if hint:
            answer = self._ask(
                f"Na lista de resultados da busca do WhatsApp, qual posição (1 = primeiro de cima) é a conversa "
                f"{'do grupo' if group else 'de'} '{contact}' que combina com esta descrição: '{hint}'? Responda só o número; 0 se nenhuma combinar."
            )
            number = _answer_number(answer)
            if number and 1 <= number <= 8:
                position = number
        for _ in range(position):
            self.keys.press("down")
            self.sleep(0.15)
        self.keys.press("enter")
        self.sleep(1.6)

    def _verify_type_send(self, contact: str, text: str, send: bool, *, typed: bool, where: str, group: bool = False) -> dict[str, Any]:
        seen = self._open_chat_name()
        same = self._same_person(contact, seen, group)
        if same is False:
            self.keys.press("esc")
            return {
                "success": False,
                "error": f"Não achei a conversa certa: procurei '{contact}' e abriu '{seen}'. Não escrevi nada.",
            }
        if not typed:
            self.keys.type_text(text)
            self.sleep(0.4)
        if send and same is True and not self.focus("WhatsApp"):
            # O foco saiu do WhatsApp enquanto digitava: Enter iria para outra janela.
            return {
                "message": f"Deixei a mensagem escrita na conversa com {seen or contact} ({where}), mas a janela perdeu o foco; "
                "não enviei. É só conferir e apertar Enter.",
                "sent": False, "chat": seen,
            }
        if not send or same is None:
            why = "" if not send else " Não consegui conferir a conversa pela tela, então não enviei sozinho."
            return {
                "message": f"Deixei a mensagem escrita na conversa com {seen or contact} ({where}).{why} É só conferir e apertar Enter.",
                "sent": False, "chat": seen,
            }
        self.keys.press("enter")
        self.sleep(1.5)
        snippet = text[:60]
        check = self._ask(f"Na conversa aberta do WhatsApp, a mensagem \"{snippet}\" aparece como enviada (balão do lado direito)? Responda só sim ou não.")
        delivered = check is not None and _plain(check).startswith("sim")
        if not delivered:
            return {
                "message": f"Apertei Enter na conversa com {seen} ({where}), mas não consegui ver a mensagem enviada. Confere?",
                "sent": None, "chat": seen,
            }
        return {"message": f"Mensagem enviada para {seen} ({where}).", "sent": True, "chat": seen}

    # WhatsApp Web num perfil do Chrome -----------------------------------------
    def _web_state(self) -> str:
        answer = self._ask(
            "Olhe a aba do WhatsApp Web no Chrome. Responda só UMA palavra: PRONTO (a lista de conversas aparece), "
            "DUPLICADO (aviso de que o WhatsApp está aberto em outra janela, com botão 'Usar aqui'), "
            "QRCODE (pede para escanear um QR code) ou CARREGANDO."
        )
        value = _plain(answer or "")
        for state in ("duplicado", "qrcode", "carregando", "pronto"):
            if state in value.replace(" ", ""):
                return state
        return "desconhecido"

    def open_web(self, profile: str = "") -> dict[str, Any]:
        """Só abre o WhatsApp Web (no perfil pedido ou no que ele está usando)."""
        if not profile or profile == CURRENT_PROFILE:
            if self.open_current(WEB_URL):
                return {"message": "Feito, senhor.", "where": "perfil atual"}
            self.open_target(WEB_URL)
            return {"message": "Feito, senhor.", "where": "navegador"}
        info = self.find_profile(profile)
        if info is None:
            names = ", ".join(self.profile_names()) or "nenhum encontrado"
            return {"success": False, "error": f"Não achei o perfil '{profile}' no Chrome. Perfis: {names}."}
        self.open_in_profile(info["dir"], WEB_URL)
        return {"message": "Feito, senhor.", "where": info.get("name")}

    def _send_web(self, contact: str, text: str, hint: str, send: bool, profile: str, group: bool = False) -> dict[str, Any]:
        stop, where = self._open_web_chat(contact, hint, profile, group)
        if stop is not None:
            return stop
        return self._verify_type_send(contact, text, send, typed=False, where=where, group=group)

    def _open_web_chat(self, contact: str, hint: str, profile: str, group: bool) -> tuple[dict[str, Any] | None, str]:
        """Abre a conversa no WhatsApp Web do perfil. Devolve (resultado final se parou, onde)."""
        if profile == CURRENT_PROFILE:
            info: dict[str, str] | None = {"dir": "", "name": "atual"}
        else:
            info = self.find_profile(profile)
        if info is None:
            names = ", ".join(self.profile_names()) or "nenhum encontrado"
            return {"success": False, "error": f"Não achei o perfil '{profile}' no Chrome. Perfis: {names}."}, ""
        where = f"WhatsApp Web, perfil {info.get('name') or profile}"
        if self.ask_screen is None:
            self.open_web(profile)
            return {"message": f"Abri o {where}. Sem a visão da tela não consigo procurar o contato sozinho.", "sent": False}, where
        # Abre (ou traz) o WhatsApp Web naquele perfil: o Chrome usa a janela desse perfil.
        if profile == CURRENT_PROFILE:
            if not self.open_current(WEB_URL):
                self.open_target(WEB_URL)
        else:
            self.open_in_profile(info["dir"], WEB_URL)
        if not self.wait_window("WhatsApp", 25.0):
            return {"success": False, "error": f"O {where} não abriu a tempo."}, where
        if not self.focus("WhatsApp"):
            return {"success": False, "error": f"Abri o {where}, mas não consegui trazer a janela para a frente. Não escrevi nada."}, where
        self.sleep(4.0)
        for _ in range(5):
            state = self._web_state()
            if state == "pronto":
                break
            if state == "qrcode":
                return {"success": False, "error": f"O {where} não está conectado: precisa escanear o QR code no celular."}, where
            if state == "duplicado":
                # Já estava aberto noutra aba desse perfil: fecha a nova e vai para a antiga.
                self.keys.hotkey("ctrl", "w")
                self.sleep(1.0)
                self.keys.hotkey("ctrl", "shift", "a")
                self.sleep(0.8)
                self.keys.type_text("WhatsApp")
                self.sleep(0.8)
                self.keys.press("enter")
                self.sleep(2.5)
                continue
            self.sleep(4.0)
        else:
            return {"success": False, "error": f"O {where} não carregou."}, where
        self.keys.press("esc")
        self.keys.hotkey("ctrl", "alt", "/")  # busca do WhatsApp Web
        self._search_and_open(contact, hint, group)
        return None, where


# Descrições sugeridas para o catálogo de ferramentas do agente (brain/agent_loop.py).
TOOL_DOCS: dict[str, tuple[str, tuple[str, ...], dict[str, Any]]] = {
    "whatsapp_send": (
        "Manda mensagem no WhatsApp para uma pessoa OU um grupo: abre o app (ou o WhatsApp Web do perfil), acha a "
        "conversa pela agenda ou pela busca (pista opcional, ex.: 'da Embralan'), confere pela tela e envia. "
        "Para grupo use contact só com o nome (ex.: 'Teste', não 'grupo Teste') e group=true. "
        "send=false só deixa escrito para o Du conferir.",
        ("contact", "text"),
        {"contact": str, "text": str, "hint": str, "send": bool, "profile": str, "group": bool},
    ),
    "whatsapp_message": (
        "Só abre o WhatsApp com a mensagem pronta (o Du escolhe a conversa e aperta Enter). Serve para pessoa ou "
        "grupo (group=true); use quando não der para conferir pela tela.",
        ("contact", "text"),
        {"contact": str, "text": str, "group": bool},
    ),
    "whatsapp_read": (
        "Lê as últimas mensagens de uma conversa do WhatsApp (pessoa ou grupo): abre a conversa, confere pela tela e "
        "devolve as últimas N mensagens como texto. Não escreve nem envia nada. Para grupo use group=true.",
        ("contact",),
        {"contact": str, "count": int, "group": bool, "hint": str, "profile": str},
    ),
}
