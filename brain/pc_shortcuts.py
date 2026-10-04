"""Atalhos diretos para as ferramentas de janelas, Windows, arquivos, web e agenda.

Frases claras ("minimiza o Chrome", "coloca o brilho em 60", "o que eu baixei por
último?") viram a ferramenta certa sem passar pelo modelo: funcionam rápido, sem
internet e com o modelo local pequeno. O que não casar aqui segue para o modelo
(e, se preciso, para o operador de tela).
"""

from __future__ import annotations

import re
from typing import Any

_POLITE = r"^(?:(?:telex|duque)[\s,!.:-]+)?(?:por favor[,]?\s+)?(?:(?:você\s+)?(?:pode|consegue|poderia)\s+)?(?:me\s+)?"
_ART = r"(?:o |a |os |as )?"
_URL = r"(?P<url>(?:https?://|www\.)\S+)"
_FOLDERS = r"(?:documentos|downloads|área de trabalho|area de trabalho|desktop|imagens|músicas|musicas|vídeos|videos)"


def _clean(value: str) -> str:
    return value.strip().strip(" .,!?;:\"'")


def _url(raw: str) -> str:
    url = raw.rstrip(".,;)!?\"'")
    return url if url.startswith("http") else "https://" + url


_RULES: list[tuple[re.Pattern[str], Any]] = []


def _rule(pattern: str):
    def register(build):
        _RULES.append((re.compile(_POLITE + "(?:" + pattern + ")", re.IGNORECASE), build))
        return build
    return register


# --- Windows / sistema ---------------------------------------------------------

@_rule(r"(?:abr[ae]|abrir|mostr[ae]|v[aá] (?:para|pra))\s+(?:as |nas )?(?:configura[çc][õo]es|configs?|ajustes)(?:\s+(?:de|do|da|das|dos)\s+(?P<page>.+))?$")
def _settings(m: re.Match[str]) -> tuple[str, dict[str, Any]]:
    return ("open_settings", {"page": _clean(m.group("page") or "")})


@_rule(r"(?:(?:coloc|p[oõ]|ponh|ajust|deix|mud)\w*|aument\w*|diminu\w*|baix\w*)\s+o brilho\s+(?:em|para|pra|no|pro)?\s*(?P<p>\d{1,3})\s*%?$")
def _brightness(m: re.Match[str]) -> tuple[str, dict[str, Any]]:
    return ("brightness_set", {"percent": max(0, min(100, int(m.group("p"))))})


@_rule(r"(?:como (?:est[aá]|t[aá]) o|status do|qual (?:é )?o) (?:wi-?fi|wifi|sinal do wi-?fi)\??$|(?:em )?qual (?:rede|wi-?fi) (?:eu )?(?:estou|to|tô) (?:conectado|ligado)\??$")
def _wifi(_m: re.Match[str]) -> tuple[str, dict[str, Any]]:
    return ("wifi_status", {})


@_rule(r"(?:tir[ae]|tirar|fa[çc]a|faz|salv[ae])\s+(?:um |uma )?(?:print|captura(?: de tela)?|screenshot)(?:\s+(?:da tela|e salv[ae]|e guard[ae]))*$")
def _screenshot(_m: re.Match[str]) -> tuple[str, dict[str, Any]]:
    return ("screenshot_save", {})


@_rule(r"(?:quais|que) (?:apps|aplicativos|programas) (?:eu )?(?:tenho|est[aã]o instalados|instalados)(?:\s+(?:com|de)\s+(?P<q>.+?))?\??$")
def _apps(m: re.Match[str]) -> tuple[str, dict[str, Any]]:
    return ("apps_list", {"query": _clean(m.group("q") or "")})


# --- Janelas --------------------------------------------------------------------

@_rule(r"(?:quais|que) janelas (?:est[aã]o |tem |t[eê]m )?(?:abertas)?\??$|(?:list[ae]|mostr[ae]) (?:as )?janelas(?: abertas)?$")
def _windows(_m: re.Match[str]) -> tuple[str, dict[str, Any]]:
    return ("windows_list", {})


@_rule(r"(?:mostr[ae]|v[aá] para|v[aá] pra) a [aá]rea de trabalho$|minimiz[ae] tudo$")
def _desktop(_m: re.Match[str]) -> tuple[str, dict[str, Any]]:
    return ("show_desktop", {})


@_rule(r"minimiz(?:[ae]|ar)\s+" + _ART + r"(?P<title>.+)$")
def _minimize(m: re.Match[str]) -> tuple[str, dict[str, Any]]:
    return ("window_minimize", {"title": _clean(m.group("title"))})


@_rule(r"maximiz(?:[ae]|ar)\s+" + _ART + r"(?P<title>.+)$")
def _maximize(m: re.Match[str]) -> tuple[str, dict[str, Any]]:
    return ("window_maximize", {"title": _clean(m.group("title"))})


@_rule(r"restaur(?:[ae]|ar)\s+(?:a janela d[oa] )?" + _ART + r"(?P<title>.+)$")
def _restore(m: re.Match[str]) -> tuple[str, dict[str, Any]]:
    return ("window_restore", {"title": _clean(m.group("title"))})


@_rule(r"(?:traz|tr[aá]z|traga|trazer|coloc[ae]|p[oõ]e|ponha)\s+" + _ART + r"(?P<title>.+?)\s+(?:para|pra|na|em)\s+(?:a )?frente$")
def _focus(m: re.Match[str]) -> tuple[str, dict[str, Any]]:
    return ("window_focus", {"title": _clean(m.group("title"))})


@_rule(r"(?:coloc[ae]|p[oõ]e|ponha|encaix[ae]|jog[ae])\s+" + _ART + r"(?P<title>.+?)\s+(?:na|para a|pra|pro lado|no lado)\s+(?:metade\s+)?(?P<side>esquerd[ao]|direit[ao])$")
def _snap(m: re.Match[str]) -> tuple[str, dict[str, Any]]:
    side = "esquerda" if m.group("side").startswith("esquerd") else "direita"
    return ("snap_window", {"title": _clean(m.group("title")), "side": side})


# --- Arquivos ---------------------------------------------------------------------

@_rule(r"(?:o que (?:eu )?baixei(?: por [uú]ltimo| recentemente| hoje)?|(?:[uú]ltimos|meus) downloads|arquivos (?:recentes|baixados)(?: d[oa]s? (?P<folder>" + _FOLDERS + r"))?)\??$")
def _recent(m: re.Match[str]) -> tuple[str, dict[str, Any]]:
    return ("recent_files", {"folder": _clean(m.group("folder") or "downloads")})


@_rule(r"(?:cri[ae]|criar|fa[çc]a|faz)\s+(?:uma |a )?(?:nova )?pasta\s+(?:chamada\s+|com o nome\s+)?(?P<name>.+?)(?:\s+(?:em|na|no|dentro de|dentro d[oa])\s+(?:pasta\s+)?(?P<parent>" + _FOLDERS + r"))?$")
def _folder(m: re.Match[str]) -> tuple[str, dict[str, Any]]:
    args: dict[str, Any] = {"name": _clean(m.group("name"))}
    if m.group("parent"):
        args["parent"] = _clean(m.group("parent"))
    return ("create_folder", args)


# --- Web --------------------------------------------------------------------------

@_rule(r"(?:baix[ae]|baixar|fa[çc]a o download d[eoa]|salv[ae])\s+(?:esse |este |o |a |essa |esta )?(?:(?:arquivo|pdf|imagem|documento|v[ií]deo)\s*)?(?:d[eoa] |em )?(?:aqui\s*)?[:]?\s*" + _URL + r"$")
def _download(m: re.Match[str]) -> tuple[str, dict[str, Any]]:
    return ("download_file", {"url": _url(m.group("url"))})


@_rule(r"(?:o )?(?:site|endere[çc]o|link)?\s*" + _URL + r"\s+(?:est[aá]|t[aá]) (?:no ar|funcionando|online|fora do ar)\??$")
def _check(m: re.Match[str]) -> tuple[str, dict[str, Any]]:
    return ("check_url", {"url": _url(m.group("url"))})


@_rule(r"(?:o )?(?:site|endere[çc]o|link) (?:est[aá]|t[aá]) (?:no ar|funcionando|online)\??[:]?\s*" + _URL + r"$")
def _check_after(m: re.Match[str]) -> tuple[str, dict[str, Any]]:
    return ("check_url", {"url": _url(m.group("url"))})


@_rule(r"(?:l[eê]|ler|leia|resum[ae]|resumir|o que diz|abr[ae] e (?:l[eê]|resum[ae]))\s+(?:esse |este |o |a |essa |esta )?(?:site|p[aá]gina|not[ií]cia|artigo|link|texto)?(?:\s+e\s+(?:me\s+)?(?:resum[ae]|diga|conta))?[:]?\s*" + _URL + r"$")
def _read(m: re.Match[str]) -> tuple[str, dict[str, Any]]:
    return ("read_webpage", {"url": _url(m.group("url"))})


# --- Mensagens e agenda ---------------------------------------------------------

@_rule(r"(?:l[eê]|ler|leia|mostr[ae]|quais s[aã]o)\s+(?:as |minhas )?(?:[uú]ltimas )?mensagens\s+d[oa]\s+(?P<group>grupo\s+)?(?:d[oa]\s+)?(?P<who>.+?)(?:\s+no (?:whatsapp|zap))?$")
def _wa_read(m: re.Match[str]) -> tuple[str, dict[str, Any]]:
    args: dict[str, Any] = {"contact": _clean(m.group("who"))}
    if m.group("group"):
        args["group"] = True
    return ("whatsapp_read", args)


@_rule(r"(?:marc[ae]|marqu[ei]|marcar|agend[ae]|agendar|cri[ae]|criar|coloc[ae]|coloqu[ei]|p[oõ]e)\s+(?:um[a]? )?(?P<what>reuni[aã]o|compromisso|evento|consulta|encontro)(?P<rest>.*?)\s+(?:na (?:minha )?agenda\s+)?(?P<when>(?:hoje|amanh[aã]|depois de amanh[aã]|segunda|ter[çc]a|quarta|quinta|sexta|s[aá]bado|domingo|dia \d{1,2}|daqui a)\b.*)$")
def _calendar(m: re.Match[str]) -> tuple[str, dict[str, Any]]:
    title = (m.group("what") + " " + _clean(m.group("rest") or "")).strip()
    title = re.sub(r"\s+na (?:minha )?agenda$", "", title)
    return ("calendar_event", {"title": title[:1].upper() + title[1:], "when": _clean(m.group("when"))})


def match(text: str) -> tuple[str, dict[str, Any]] | None:
    """(ferramenta, argumentos) para uma frase clara; None quando não é um destes atalhos."""
    value = " ".join((text or "").split()).rstrip(" .!")
    if not value:
        return None
    for pattern, build in _RULES:
        found = pattern.match(value)
        if found:
            return build(found)
    return None
