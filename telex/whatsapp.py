"""WhatsApp Web pelo navegador do TELEX.

Sempre pelo site (nunca o app do Windows, nem a Microsoft Store). A busca usa
a caixa "Pesquisar" do próprio WhatsApp, a conversa só é usada depois de
conferir o nome no topo, e o envio é conferido na última mensagem enviada.

O WhatsApp muda o HTML de tempos em tempos; por isso cada peça tem vários
seletores. Se todos falharem, o erro diz isso e o agente ainda pode usar as
ferramentas genéricas da página (listar elementos, clicar, digitar).
"""

from __future__ import annotations

import re
import time
import unicodedata
from typing import Any

from .browser import Browser

URL = "https://web.whatsapp.com/"
HOST = "web.whatsapp.com"

SEARCH_BOX = (
    '#side [contenteditable="true"][role="textbox"]',
    '#side input[role="textbox"]',
    '#side input[type="text"]',
    '#side [contenteditable="true"]',
    '[aria-label="Pesquisar ou começar uma nova conversa"]',
    '[aria-label*="Pesquisar"][contenteditable="true"]',
    'input[aria-label*="Pesquisar"]',
    '[aria-label*="Search"][contenteditable="true"]',
    'input[aria-label*="Search"]',
)
COMPOSE_BOX = (
    '#main footer [contenteditable="true"][role="textbox"]',
    '#main footer [contenteditable="true"]',
    'footer [contenteditable="true"]',
    '[aria-label*="Digite uma mensagem"]',
    '[aria-label*="Type a message"]',
)
CHAT_TITLES = '#pane-side span[title], [aria-label*="Lista de conversas"] span[title], [aria-label*="Chat list"] span[title]'
LOGGED_IN = "#side, #pane-side"
QR_CODE = 'canvas[aria-label*="QR"], canvas[aria-label*="Scan"], div[data-ref] canvas, [data-testid="qrcode"]'


def plain(text: str) -> str:
    value = unicodedata.normalize("NFKD", (text or "").casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^\w\s]", " ", value).split())


def best_match(wanted: str, titles: list[str]) -> str | None:
    """O título que corresponde ao nome pedido: exato > começa com > contém > todas as palavras."""
    target = plain(wanted)
    if not target:
        return None
    normalized = [(title, plain(title)) for title in titles if title.strip()]
    for test in (
        lambda value: value == target,
        lambda value: value.startswith(target + " ") or value.startswith(target),
        lambda value: f" {target} " in f" {value} ",
        lambda value: target in value,
        lambda value: all(word in value.split() for word in target.split()),
    ):
        found = [title for title, value in normalized if test(value)]
        if found:
            return min(found, key=len)
    return None


def _first(page: Any, selectors: tuple[str, ...], timeout: float = 4.0) -> Any | None:
    deadline = time.monotonic() + timeout
    while True:
        for selector in selectors:
            locator = page.locator(selector)
            try:
                if locator.count() and locator.first.is_visible():
                    return locator.first
            except Exception:
                continue
        if time.monotonic() >= deadline:
            return None
        page.wait_for_timeout(250)


def _ready(browser: Browser) -> Any:
    """A aba do WhatsApp Web pronta (logada). Levanta com instrução clara se pedir o QR code."""
    page = browser.page_for(HOST, URL)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            if page.locator(LOGGED_IN).count():
                page.wait_for_timeout(500)
                return page
            if page.locator(QR_CODE).count():
                raise RuntimeError(
                    "O WhatsApp Web está pedindo para conectar. Abri a janela do TELEX: escaneie o QR code "
                    "pelo celular (WhatsApp > Aparelhos conectados) uma única vez e peça de novo."
                )
        except RuntimeError:
            raise
        except Exception:
            pass
        page.wait_for_timeout(500)
    raise RuntimeError("O WhatsApp Web não terminou de carregar em 60 segundos.")


def _visible_titles(page: Any) -> list[str]:
    titles: list[str] = []
    for item in page.locator(CHAT_TITLES).all()[:40]:
        try:
            title = item.get_attribute("title") or ""
        except Exception:
            continue
        if title and title not in titles:
            titles.append(title)
    return titles


def _header_title(page: Any) -> str:
    for selector in ("#main header span[title]", "#main header [title]", "#main header"):
        locator = page.locator(selector)
        try:
            if locator.count():
                return (locator.first.get_attribute("title") or locator.first.inner_text() or "").strip()
        except Exception:
            continue
    return ""


def _clear_search(page: Any) -> None:
    box = _first(page, SEARCH_BOX, timeout=1.0)
    if box is not None:
        try:
            box.click()
            page.keyboard.press("Control+A")
            page.keyboard.press("Delete")
            page.keyboard.press("Escape")
        except Exception:
            pass


def open_chat(browser: Browser, name: str) -> dict[str, Any]:
    """Abre a conversa ``name`` pela pesquisa do WhatsApp e confere o nome no topo."""
    wanted = (name or "").strip()
    if not wanted:
        raise ValueError("Diga o nome do contato ou do grupo.")
    page = _ready(browser)
    if best_match(wanted, [_header_title(page)]):
        return {"ok": True, "conversa": _header_title(page)}
    box = _first(page, SEARCH_BOX)
    if box is None:
        raise RuntimeError("Não achei a caixa de pesquisa do WhatsApp Web (o site pode ter mudado).")
    box.click()
    page.keyboard.press("Control+A")
    page.keyboard.press("Delete")
    page.keyboard.insert_text(wanted)
    match: str | None = None
    titles: list[str] = []
    for _ in range(16):  # até ~4 s para os resultados aparecerem
        page.wait_for_timeout(250)
        titles = _visible_titles(page)
        match = best_match(wanted, titles)
        if match:
            break
    if not match:
        _clear_search(page)
        shown = ", ".join(titles[:8]) or "nenhum"
        return {"ok": False, "erro": f"Não encontrei '{wanted}' no WhatsApp. Resultados que apareceram: {shown}."}
    side = page.locator("#pane-side")
    target = side.get_by_title(match, exact=True) if side.count() else page.get_by_title(match, exact=True)
    target.first.click()
    for _ in range(20):
        page.wait_for_timeout(250)
        header = _header_title(page)
        if header and best_match(match, [header]):
            _clear_search(page)  # a lista de conversas volta a mostrar todas
            return {"ok": True, "conversa": header}
    return {"ok": False, "erro": f"Cliquei em '{match}', mas a conversa não abriu."}


def _last_outgoing(page: Any) -> str:
    locator = page.locator("#main .message-out")
    try:
        count = locator.count()
        return locator.nth(count - 1).inner_text() if count else ""
    except Exception:
        return ""


def send_message(browser: Browser, name: str, text: str) -> dict[str, Any]:
    message = (text or "").strip()
    if not message:
        raise ValueError("A mensagem está vazia.")
    opened = open_chat(browser, name)
    if not opened.get("ok"):
        return opened
    page = browser.page
    box = _first(page, COMPOSE_BOX)
    if box is None:
        raise RuntimeError("A conversa abriu, mas não achei a caixa de mensagem. Não enviei nada.")
    before = _last_outgoing(page)
    box.click()
    lines = message.split("\n")
    for index, line in enumerate(lines):
        if line:
            page.keyboard.insert_text(line)
        if index < len(lines) - 1:
            page.keyboard.press("Shift+Enter")
    page.keyboard.press("Enter")
    probe = plain(next((line for line in lines if line.strip()), ""))[:30]
    for _ in range(20):
        page.wait_for_timeout(250)
        last = _last_outgoing(page)
        if last != before and probe and probe in plain(last):
            return {"ok": True, "conversa": opened["conversa"], "enviado": True}
    return {"ok": False, "conversa": opened["conversa"], "erro": "Apertei enviar, mas não consegui confirmar a mensagem na conversa."}


def read_messages(browser: Browser, name: str, count: int = 10) -> dict[str, Any]:
    opened = open_chat(browser, name)
    if not opened.get("ok"):
        return opened
    page = browser.page
    page.wait_for_timeout(800)
    items: list[str] = []
    for bubble in page.locator("#main [data-pre-plain-text]").all()[-max(1, min(int(count), 40)):]:
        try:
            meta = (bubble.get_attribute("data-pre-plain-text") or "").strip()  # "[10:32, 07/10/2026] Fulano: "
            body = bubble.inner_text().strip()
        except Exception:
            continue
        if body:
            items.append(f"{meta} {body}".strip())
    return {"ok": True, "conversa": opened["conversa"], "mensagens": items}


def recent_chats(browser: Browser, count: int = 10) -> dict[str, Any]:
    page = _ready(browser)
    _clear_search(page)
    page.wait_for_timeout(400)
    rows: list[str] = []
    for row in page.locator('#pane-side [role="listitem"], #pane-side [role="row"]').all()[: max(1, min(int(count), 30))]:
        try:
            text = " | ".join(part.strip() for part in row.inner_text().split("\n") if part.strip())
        except Exception:
            continue
        if text:
            rows.append(text)
    return {"ok": True, "conversas": rows}
