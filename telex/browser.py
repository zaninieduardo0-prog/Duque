"""Navegador do TELEX: um Chrome próprio controlado por código (Playwright).

Por que não "às cegas" com teclado e mouse: o Playwright fala direto com a
página. A digitação vai para o campo certo (nunca para a barra do Google), dá
para ler o texto da página sem OCR e conferir o resultado de cada ação.

O perfil fica em ``duque_data/navegador``: o login do WhatsApp Web e dos sites
é feito uma vez e continua salvo. Ele é separado do Chrome do Du, então os
dois podem ficar abertos ao mesmo tempo.

O Playwright (API síncrona) só pode ser usado pela thread que o iniciou; por
isso todo pedido passa por uma thread dedicada (``call``).
"""

from __future__ import annotations

import os
import queue
import re
import threading
from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = Path(os.getenv("TELEX_PERFIL_NAVEGADOR", str(ROOT / "duque_data" / "navegador")))
MAX_TEXT = 6000

# Marca e lista os elementos com que dá para interagir (links, botões, campos).
# Cada um ganha um número (data-telex-id) para "clicar 3" / "digitar no 5".
_ELEMENTS_JS = r"""
(limit) => {
  const sel = 'a[href], button, input:not([type=hidden]), textarea, select, [role=button], [role=link], [role=textbox], [role=searchbox], [role=tab], [role=menuitem], [role=option], [role=checkbox], [contenteditable=true]';
  const out = [];
  let n = 0;
  document.querySelectorAll('[data-telex-id]').forEach(e => e.removeAttribute('data-telex-id'));
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2 || r.bottom < 0 || r.top > innerHeight * 3) continue;
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none') continue;
    n += 1;
    el.setAttribute('data-telex-id', String(n));
    const label = (el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('placeholder') || el.innerText || el.value || el.getAttribute('alt') || '').trim().replace(/\s+/g, ' ').slice(0, 80);
    const kind = el.getAttribute('role') || el.tagName.toLowerCase() + (el.type ? ':' + el.type : '');
    out.push(n + ' [' + kind + '] ' + label);
    if (out.length >= limit) break;
  }
  return out;
}
"""


def normalize_url(url: str) -> str:
    value = (url or "").strip()
    if not value:
        raise ValueError("Endereço vazio.")
    if re.match(r"^[a-z][a-z0-9+.-]*://", value, re.IGNORECASE):
        if not value.lower().startswith(("http://", "https://")):
            raise ValueError("Só abro endereços http/https.")
        return value
    if " " in value or "." not in value:
        # Não parece endereço: vira pesquisa.
        return "https://www.google.com/search?q=" + quote_plus(value)
    return "https://" + value


class Browser:
    """Um Chrome do TELEX, com todas as chamadas numa thread só."""

    def __init__(self, profile_dir: Path = PROFILE_DIR, headless: bool | None = None) -> None:
        self.profile_dir = Path(profile_dir)
        self.headless = headless if headless is not None else os.getenv("TELEX_NAVEGADOR_OCULTO", "0") == "1"
        self._jobs: queue.Queue[tuple[Callable[..., Any], tuple[Any, ...], Future[Any]] | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._context: Any = None
        self._playwright: Any = None
        self.page: Any = None  # aba "atual" (a última usada)

    # thread dedicada -------------------------------------------------------------
    def call(self, function: Callable[..., Any], *args: Any, timeout: float = 120.0) -> Any:
        """Roda ``function(self, *args)`` na thread do navegador e devolve o resultado."""
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, name="telex-navegador", daemon=True)
                self._thread.start()
        future: Future[Any] = Future()
        self._jobs.put((function, args, future))
        return future.result(timeout=timeout)

    def _loop(self) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                break
            function, args, future = job
            try:
                future.set_result(function(self, *args))
            except BaseException as exc:  # noqa: BLE001 - o erro volta para quem chamou
                future.set_exception(exc)
        self._shutdown()

    def close(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            self._jobs.put(None)

    # contexto (só na thread do navegador) ----------------------------------------
    def context(self) -> Any:
        if self._context is not None:
            return self._context
        from playwright.sync_api import sync_playwright

        if self._playwright is None:
            self._playwright = sync_playwright().start()
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        options: dict[str, Any] = {
            "headless": self.headless,
            "no_viewport": True,
            "locale": "pt-BR",
            "args": ["--start-maximized", "--disable-blink-features=AutomationControlled"],
        }
        last_error: Exception | None = None
        # Usa o Chrome (ou Edge) instalado; o Chromium do Playwright é o último recurso.
        # TELEX_NAVEGADOR_EXECUTAVEL aponta um navegador específico (ex.: nos testes).
        executable = os.getenv("TELEX_NAVEGADOR_EXECUTAVEL", "").strip()
        attempts: list[dict[str, Any]] = [{"executable_path": executable}] if executable else []
        attempts += [{"channel": "chrome"}, {"channel": "msedge"}, {}]
        for extra in attempts:
            try:
                self._context = self._playwright.chromium.launch_persistent_context(str(self.profile_dir), **options, **extra)
                break
            except Exception as exc:
                last_error = exc
        if self._context is None:
            raise RuntimeError(f"Não consegui abrir o navegador do TELEX: {last_error}")
        self._context.set_default_timeout(15000)
        # Se o Du fechar a janela, o próximo pedido abre outra (em vez de falhar para sempre).
        self._context.on("close", lambda *_: setattr(self, "_context", None))
        self.page = self._context.pages[0] if self._context.pages else None
        return self._context

    def _shutdown(self) -> None:
        try:
            if self._context is not None:
                self._context.close()
        except Exception:
            pass
        try:
            if self._playwright is not None:
                self._playwright.stop()
        except Exception:
            pass
        self._context = self._playwright = self.page = None

    def current_page(self) -> Any:
        context = self.context()
        if self.page is None or self.page.is_closed():
            open_pages = [page for page in context.pages if not page.is_closed()]
            self.page = open_pages[-1] if open_pages else context.new_page()
        return self.page

    def page_for(self, host: str, url: str) -> Any:
        """A aba que já está em ``host`` (reaproveita) ou uma nova aberta em ``url``."""
        context = self.context()
        for page in context.pages:
            if not page.is_closed() and host in (page.url or ""):
                self.page = page
                page.bring_to_front()
                return page
        page = self.current_page()
        if page.url not in ("about:blank", "", "chrome://newtab/"):
            page = context.new_page()  # o site que estava aberto continua na aba dele
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.bring_to_front()
        self.page = page
        return page

    def reusable_page(self) -> Any:
        """A aba atual para navegar; só abre outra para não sair do WhatsApp (e não acumular abas)."""
        page = self.current_page()
        if "web.whatsapp.com" in (page.url or ""):
            others = [p for p in self.context().pages if not p.is_closed() and "web.whatsapp.com" not in (p.url or "")]
            page = others[-1] if others else self.context().new_page()
        return page


# Ferramentas de navegador (cada função roda na thread do navegador) ------------------

def _summary(page: Any) -> dict[str, Any]:
    try:
        title = page.title()
    except Exception:
        title = ""
    return {"titulo": title, "url": page.url}


def open_site(browser: Browser, url: str) -> dict[str, Any]:
    target = normalize_url(url)
    page = browser.reusable_page()
    page.goto(target, wait_until="domcontentloaded", timeout=45000)
    page.bring_to_front()
    browser.page = page
    return {"ok": True, **_summary(page)}


def google_search(browser: Browser, query: str) -> dict[str, Any]:
    if not (query or "").strip():
        raise ValueError("Pesquisa vazia.")
    result = open_site(browser, "https://www.google.com/search?q=" + quote_plus(query.strip()))
    page = browser.page
    links: list[dict[str, str]] = []
    try:
        page.wait_for_selector("a h3", timeout=8000)
        for anchor in page.locator("a:has(h3)").all()[:8]:
            title = anchor.locator("h3").first.inner_text().strip()
            href = anchor.get_attribute("href") or ""
            if title and href.startswith("http"):
                links.append({"titulo": title, "url": href})
    except Exception:
        pass
    return {**result, "resultados": links}


def read_page(browser: Browser, max_chars: int = MAX_TEXT) -> dict[str, Any]:
    page = browser.current_page()
    text = page.locator("body").inner_text(timeout=10000)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    limit = max(500, min(int(max_chars), 20000))
    return {**_summary(page), "texto": text[:limit], "cortado": len(text) > limit}


def list_elements(browser: Browser, limit: int = 80) -> dict[str, Any]:
    page = browser.current_page()
    items = page.evaluate(_ELEMENTS_JS, max(10, min(int(limit), 200)))
    return {**_summary(page), "elementos": items}


def _element(browser: Browser, number: int) -> Any:
    page = browser.current_page()
    locator = page.locator(f'[data-telex-id="{int(number)}"]')
    if locator.count() == 0:
        raise ValueError(f"Não achei o elemento {number}. Liste os elementos de novo (a página mudou).")
    return locator.first


def click_element(browser: Browser, number: int) -> dict[str, Any]:
    element = _element(browser, number)
    element.scroll_into_view_if_needed(timeout=5000)
    element.click(timeout=8000)
    page = browser.current_page()
    page.wait_for_timeout(800)
    # Clique que abriu outra aba: segue nela.
    pages = [p for p in browser.context().pages if not p.is_closed()]
    if pages and pages[-1] is not page:
        browser.page = pages[-1]
        browser.page.bring_to_front()
    return {"ok": True, **_summary(browser.page)}


def type_into(browser: Browser, number: int, text: str, enter: bool = False) -> dict[str, Any]:
    element = _element(browser, number)
    element.click(timeout=8000)
    page = browser.current_page()
    page.keyboard.press("Control+A")
    page.keyboard.press("Delete")
    page.keyboard.insert_text(text)
    if enter:
        page.keyboard.press("Enter")
        page.wait_for_timeout(1000)
    return {"ok": True, **_summary(page)}


def press_key(browser: Browser, key: str) -> dict[str, Any]:
    page = browser.current_page()
    page.keyboard.press(key)
    page.wait_for_timeout(500)
    return {"ok": True, **_summary(page)}


def go_back(browser: Browser) -> dict[str, Any]:
    page = browser.current_page()
    page.go_back(wait_until="domcontentloaded")
    return {"ok": True, **_summary(page)}


def list_tabs(browser: Browser) -> dict[str, Any]:
    pages = [p for p in browser.context().pages if not p.is_closed()]
    return {"abas": [f"{index} {p.title()} — {p.url}" for index, p in enumerate(pages, start=1)]}


def switch_tab(browser: Browser, number: int) -> dict[str, Any]:
    pages = [p for p in browser.context().pages if not p.is_closed()]
    if not 1 <= int(number) <= len(pages):
        raise ValueError(f"Aba inválida: escolha de 1 a {len(pages)}.")
    browser.page = pages[int(number) - 1]
    browser.page.bring_to_front()
    return {"ok": True, **_summary(browser.page)}


def close_tab(browser: Browser) -> dict[str, Any]:
    page = browser.current_page()
    if "web.whatsapp.com" in (page.url or ""):
        raise ValueError("Não fecho a aba do WhatsApp (o login dele fica nela).")
    page.close()
    browser.page = None
    return {"ok": True}
