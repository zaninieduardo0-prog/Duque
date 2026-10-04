"""Rascunhos prontos por link: e-mail, evento na agenda e compartilhar texto.

Nada é enviado sozinho: cada ferramenta só abre a página já preenchida
(Gmail, Outlook, Google Agenda, WhatsApp, Telegram, X) para o Du conferir e
mandar. Por isso o risco de todas é baixo.
"""

from __future__ import annotations

import urllib.parse
from datetime import datetime, timedelta
from typing import Any, Callable

from brain.when import describe_moment, parse_when

_PROVIDERS = {
    "gmail": "gmail", "google": "gmail",
    "outlook": "outlook", "hotmail": "outlook", "live": "outlook",
    "padrao": "mailto", "padrão": "mailto", "mailto": "mailto", "default": "mailto", "": "gmail",
}
_TARGETS = {
    "whatsapp": "whatsapp", "zap": "whatsapp", "whats": "whatsapp",
    "email": "email", "e-mail": "email", "mail": "email",
    "telegram": "telegram",
    "twitter": "twitter", "x": "twitter",
}


def _query(params: dict[str, str]) -> str:
    """Parâmetros codificados com %20 (não "+"): funciona em mailto: e em todos os sites."""
    return urllib.parse.urlencode({k: v for k, v in params.items() if v}, quote_via=urllib.parse.quote)


def email_url(to: str = "", subject: str = "", body: str = "", provider: str = "gmail") -> str | None:
    kind = _PROVIDERS.get((provider or "").strip().casefold())
    if kind is None:
        return None
    to = ",".join(part.strip() for part in (to or "").replace(";", ",").split(",") if part.strip())
    if kind == "gmail":
        return "https://mail.google.com/mail/?" + _query({"view": "cm", "fs": "1", "to": to, "su": subject, "body": body})
    if kind == "outlook":
        return "https://outlook.live.com/mail/0/deeplink/compose?" + _query({"to": to, "subject": subject, "body": body})
    query = _query({"subject": subject, "body": body})
    return "mailto:" + urllib.parse.quote(to, safe="@,") + ("?" + query if query else "")


def calendar_url(title: str, start: datetime, end: datetime, details: str = "") -> str:
    dates = f"{start:%Y%m%dT%H%M%S}/{end:%Y%m%dT%H%M%S}"
    params = {"action": "TEMPLATE", "text": title, "dates": dates, "details": details}
    return "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode(
        {k: v for k, v in params.items() if v}, quote_via=urllib.parse.quote, safe="/",
    )


def share_url(text: str, target: str) -> str | None:
    kind = _TARGETS.get((target or "").strip().casefold())
    if kind == "whatsapp":
        return "https://wa.me/?" + _query({"text": text})
    if kind == "email":
        return "mailto:?" + _query({"body": text})
    if kind == "telegram":
        return "https://t.me/share/url?url=&" + _query({"text": text})
    if kind == "twitter":
        return "https://twitter.com/intent/tweet?" + _query({"text": text})
    return None


class ComposeLinks:
    SPECS: list[tuple[str, str, tuple[str, ...], dict[str, Any]]] = [
        ("email_compose",
         "Deixa um e-mail pronto (destinatário, assunto e texto) no Gmail, Outlook ou no programa de e-mail padrão "
         "(provider: gmail, outlook ou padrao). Não envia: o Du confere e manda.",
         (), {"to": str, "subject": str, "body": str, "provider": str}),
        ("calendar_event",
         "Abre o Google Agenda com um evento preenchido (título, quando — ex.: 'amanhã às 9h', 'sexta 18:30' —, "
         "duração em minutos e detalhes) para o Du salvar.",
         ("title", "when"), {"title": str, "when": str, "duration_minutes": int, "details": str}),
        ("share_text",
         "Abre o compartilhamento de um texto já preenchido em whatsapp (escolher a conversa), email, telegram ou "
         "twitter/x. Não publica nem envia sozinho.",
         ("text", "target"), {"text": str, "target": str}),
    ]
    RISK: dict[str, str] = {"email_compose": "low", "calendar_event": "low", "share_text": "low"}

    def __init__(self, open_url: Callable[[str], Any], now: Callable[[], datetime] = datetime.now) -> None:
        self.open_url = open_url
        self.now = now

    def _open(self, url: str, message: str) -> dict[str, Any]:
        try:
            outcome = self.open_url(url)
        except Exception as exc:
            return {"success": False, "error": f"Não consegui abrir o navegador: {exc}", "url": url}
        if outcome is False or (isinstance(outcome, dict) and outcome.get("success") is False):
            error = outcome.get("error") if isinstance(outcome, dict) else None
            return {"success": False, "error": error or "Não consegui abrir o navegador.", "url": url}
        return {"opened": True, "url": url, "message": message}

    def email_compose(self, to: str = "", subject: str = "", body: str = "", provider: str = "gmail") -> dict[str, Any]:
        if not (to or "").strip() and not (subject or "").strip() and not (body or "").strip():
            return {"success": False, "error": "Para quem é o e-mail e o que ele diz?"}
        url = email_url(to, subject, body, provider)
        if url is None:
            return {"success": False, "error": f"Não conheço o e-mail '{provider}'. Use gmail, outlook ou padrao."}
        who = f" para {to.strip()}" if (to or "").strip() else ""
        return self._open(url, f"Deixei o e-mail pronto{who}. É só conferir e enviar.")

    def calendar_event(self, title: str, when: str, duration_minutes: int = 60, details: str = "") -> dict[str, Any]:
        title = (title or "").strip()
        if not title:
            return {"success": False, "error": "Qual é o nome do evento?"}
        now = self.now()
        parsed = parse_when(when or "", now)
        if parsed is None:
            return {"success": False, "error": f"Não entendi quando é o evento: '{when}'. Ex.: 'amanhã às 9h'."}
        try:
            minutes = int(duration_minutes)
        except (TypeError, ValueError):
            minutes = 60
        minutes = minutes if minutes > 0 else 60
        start = parsed.moment
        end = start + timedelta(minutes=minutes)
        url = calendar_url(title, start, end, details or "")
        return {
            **self._open(url, f"Deixei o evento '{title}' pronto na agenda para {describe_moment(start, now)}. É só salvar."),
            "start": start.isoformat(timespec="minutes"), "end": end.isoformat(timespec="minutes"),
        }

    def share_text(self, text: str, target: str) -> dict[str, Any]:
        if not (text or "").strip():
            return {"success": False, "error": "O texto para compartilhar está vazio."}
        url = share_url(text.strip(), target)
        if url is None:
            return {"success": False, "error": f"Não sei compartilhar em '{target}'. Use whatsapp, email, telegram ou twitter."}
        name = {"whatsapp": "WhatsApp", "email": "e-mail", "telegram": "Telegram", "twitter": "X (Twitter)"}[_TARGETS[target.strip().casefold()]]
        return self._open(url, f"Deixei o texto pronto para compartilhar no {name}. É só escolher para quem e enviar.")

    def register(self, executor: Any, schemas: Any | None = None) -> None:
        from brain.tool_schema import ToolSpec

        for name, description, required, types in self.SPECS:
            executor.register(name, getattr(self, name))
            if schemas is not None:
                schemas.register(ToolSpec(name, description, required, types))
