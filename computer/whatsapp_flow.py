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


_SEND_VERBS = r"encaminh\w*|mand[ae]\w*|envi[ae]\w*|diga|diz|fal[ae]"
_WRITE_VERBS = r"escrev\w*|digit\w*|prepar\w*|deix[ae] escrit\w*"
_VERBS = rf"{_SEND_VERBS}|{_WRITE_VERBS}"

# "... procure pelo Otávio que trabalha comigo na Embralan, e encaminhe a mensagem X"
_SEARCH_FORM = re.compile(
    r"(?:procur\w*|busc\w*|ach[ae]\w*|encontr\w*|localiz\w*|abr\w* (?:a )?conversa (?:com|d[oa]))\s+"
    r"(?:(?:pel[oa]|por|o|a)\s+)?(?P<who>.+?)\s*(?:,\s*|\s+)(?:e\s+)?(?:depois\s+|ent[aã]o\s+|a[ií]\s+)?"
    rf"(?P<verb>{_VERBS})[\s:]+(?P<rest>.+)$",
    re.IGNORECASE | re.DOTALL,
)
# "mande (no WhatsApp) para o Otávio: X" / "manda uma mensagem pro Otávio dizendo que X"
_TO_FORM = re.compile(
    rf"(?P<verb>{_VERBS})\s+(?:uma |a )?(?:mensagem|msg|recado)?\s*(?:(?:no|pelo) (?:whats\s?app|zap)\s+)?"
    r"(?:para|pro|pra|ao|à)\s+(?:o |a )?(?P<who>.+?)(?:\s+(?:no|pelo) (?:whats\s?app|zap))?"
    r"(?:\s+(?:dizendo(?: que)?|falando(?: que)?|com o texto|escrito|que)\s+|\s*:\s*)(?P<rest>.+)$",
    re.IGNORECASE | re.DOTALL,
)


def _clean_text(rest: str) -> str:
    text = rest.strip()
    text = re.sub(r"^(?:a |uma )?(?:seguinte )?(?:mensagem|msg|recado|texto)\b\s*(?:no whats\s?app|no zap)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^(?:dizendo|falando|escrito|com o texto)(?: que)?\s+", "", text, flags=re.IGNORECASE)
    text = text.lstrip(":,- ").strip()
    if len(text) >= 2 and text[0] in "\"“'" and text[-1] in "\"”'":
        text = text[1:-1].strip()
    return text


def _split_who(who: str) -> tuple[str, str]:
    """"Otávio que trabalha comigo na Embralan" → ("Otávio", "trabalha comigo na Embralan")."""
    who = re.sub(r"\s+(?:no|pelo) (?:whats\s?app|zap)\b", "", who.strip(" ,.:"), flags=re.IGNORECASE)
    for pattern in (r"\s*,?\s+que\s+", r"\s*,\s*", r"\s+(?:l[aá] )?(?:da|do)\s+"):
        parts = re.split(pattern, who, maxsplit=1)
        if len(parts) == 2 and parts[0].strip():
            return parts[0].strip(), parts[1].strip(" ,.")
    return who, ""


def parse_request(text: str) -> WhatsAppRequest | None:
    """Contato, pista, texto e se é para enviar. None se a frase não é um envio de mensagem."""
    body = re.sub(r"^\s*(?:telex[\s,!.:-]+)?", "", text.strip(), flags=re.IGNORECASE)
    body = re.sub(r"^(?:por favor[,]?\s+)?(?:abr[ae]|abrir|abre)\s+o\s+(?:whats\s?app|zap)\s*(?:,\s*|\s+e\s+)?", "", body, flags=re.IGNORECASE)
    for form in (_SEARCH_FORM, _TO_FORM):
        match = form.search(body)
        if not match:
            continue
        contact, hint = _split_who(match.group("who"))
        message = _clean_text(match.group("rest"))
        if not contact or not message:
            continue
        send = not re.fullmatch(_WRITE_VERBS, match.group("verb"), flags=re.IGNORECASE)
        return WhatsAppRequest(contact, hint, message, send)
    return None


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
    def _same_person(contact: str, seen: str | None) -> bool | None:
        if seen is None:
            return None
        wanted = _plain(contact).split()
        shown = _plain(seen)
        return bool(wanted) and wanted[0] in shown.split() and "nenhuma" not in shown.split()

    # fluxo --------------------------------------------------------------------
    def whatsapp_send(self, contact: str, text: str, hint: str = "", send: bool = True) -> dict[str, Any]:
        contact, text = (contact or "").strip(), (text or "").strip()
        if not contact or not text:
            return {"success": False, "error": "Preciso do contato e do texto da mensagem."}
        if self.ask_screen is None and self.without_vision is not None:
            return self.without_vision(contact, text)

        phone = self.phone_of(contact)
        if phone:
            url = "whatsapp://send?" + urllib.parse.urlencode({"phone": phone, "text": text}, quote_via=urllib.parse.quote)
            self.open_target(url)
            typed = True  # o link já deixa o texto na caixa da conversa
        else:
            try:
                self.open_app("whatsapp")
            except Exception as exc:
                return {"success": False, "error": f"Não consegui abrir o WhatsApp: {exc}"}
            typed = False
        if not self.wait_window("WhatsApp", 20.0):
            return {"success": False, "error": "O WhatsApp não abriu a tempo."}
        self.focus("WhatsApp")
        self.sleep(2.0)

        if not phone:
            self.keys.press("esc")
            self.keys.hotkey("ctrl", "f")
            self.sleep(0.6)
            self.keys.type_text(contact)
            self.sleep(2.0)
            position = 1
            if hint:
                answer = self._ask(
                    f"Na lista de resultados da busca do WhatsApp, qual posição (1 = primeiro de cima) é a conversa de "
                    f"'{contact}' que combina com esta descrição: '{hint}'? Responda só o número; 0 se nenhuma combinar."
                )
                number = _answer_number(answer)
                if number and 1 <= number <= 8:
                    position = number
            for _ in range(position):
                self.keys.press("down")
                self.sleep(0.15)
            self.keys.press("enter")
            self.sleep(1.6)

        seen = self._open_chat_name()
        same = self._same_person(contact, seen)
        if same is False:
            self.keys.press("esc")
            return {
                "success": False,
                "error": f"Não achei a conversa certa: procurei '{contact}' e abriu '{seen}'. Não escrevi nada.",
            }

        if not typed:
            self.keys.type_text(text)
            self.sleep(0.4)

        if not send or same is None:
            why = "" if not send else " Não consegui conferir a conversa pela tela, então não enviei sozinho."
            return {
                "message": f"Deixei a mensagem escrita na conversa com {seen or contact}.{why} É só conferir e apertar Enter.",
                "sent": False, "chat": seen,
            }

        self.keys.press("enter")
        self.sleep(1.5)
        snippet = text[:60]
        check = self._ask(f"Na conversa aberta do WhatsApp, a mensagem \"{snippet}\" aparece como enviada (balão do lado direito)? Responda só sim ou não.")
        delivered = check is not None and _plain(check).startswith("sim")
        if not delivered:
            return {
                "message": f"Apertei Enter na conversa com {seen}, mas não consegui ver a mensagem enviada. Confere o WhatsApp?",
                "sent": None, "chat": seen,
            }
        return {"message": f"Mensagem enviada para {seen} no WhatsApp.", "sent": True, "chat": seen}
