from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from urllib.request import Request, urlopen

from .apps import resolve_app
from .controller import ComputerController


class _SearchParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._title = ""
        self._href = ""
        self._capture = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        values = dict(attrs)
        href = values.get("href") or ""
        classes = values.get("class") or ""
        if "result__a" in classes:
            self._href = href
            self._title = ""
            self._capture = True

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._title += data.strip()

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._capture:
            if self._title and self._href:
                self.results.append({"title": self._title, "url": self._href})
            self._capture = False


def _normalize_search_url(href: str) -> str:
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    query = parse_qs(parsed.query)
    redirected = query.get("uddg")
    if redirected:
        return unquote(redirected[0])
    return href


class ComputerTools:
    """Ferramentas de computador expostas ao executor, sem shell arbitrário."""

    def __init__(self, controller: ComputerController | None = None) -> None:
        self.controller = controller or ComputerController()

    def web_search(self, query: str) -> dict[str, Any]:
        query = query.strip()
        if not query:
            raise ValueError("query não pode ser vazio")
        url = "https://html.duckduckgo.com/html/?q=" + quote_plus(query)
        request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=15) as response:
            html = response.read().decode("utf-8", errors="replace")
        parser = _SearchParser()
        parser.feed(html)
        results = [
            {"title": item["title"], "url": _normalize_search_url(item["url"])}
            for item in parser.results[:8]
        ]
        payload = {"query": query, "results": results, "count": len(results)}
        self._last_search = payload
        return payload

    def open_search_result(self, index: int = 1) -> dict[str, Any]:
        if self._last_search is None:
            raise ValueError("Nenhuma pesquisa recente disponível.")
        results = self._last_search.get("results", [])
        if not isinstance(results, list) or not results:
            raise ValueError("A pesquisa recente não retornou resultados.")
        position = int(index)
        if position < 1 or position > len(results):
            raise ValueError(f"Resultado inválido. Escolha entre 1 e {len(results)}.")
        result = results[position - 1]
        if not isinstance(result, dict):
            raise ValueError("Resultado de pesquisa inválido.")
        url = str(result.get("url") or "").strip()
        if not url:
            raise ValueError("O resultado selecionado não possui URL.")
        self.controller.open_url(url)
        return {"index": position, "title": str(result.get("title") or ""), "url": url, "opened": True}

    def open_app(self, name: str) -> dict[str, Any]:
        command = resolve_app(name)
        if not command:
            raise ValueError(f"Aplicativo não encontrado: {name}")
        self.controller.launch(command)
        return {"app": name, "command": command, "opened": True}

    def open_url(self, url: str) -> dict[str, Any]:
        if not url.startswith(("http://", "https://")):
            raise ValueError("URL deve começar com http:// ou https://")
        self.controller.open_url(url)
        return {"url": url, "opened": True}

    def open_path(self, path: str) -> dict[str, Any]:
        target = Path(path).expanduser()
        if not target.exists():
            raise FileNotFoundError(f"Caminho não encontrado: {target}")
        self.controller.open_path(target)
        return {"path": str(target), "opened": True}

    def register(self, executor: Any) -> None:
        executor.register("web_search", self.web_search)
        executor.register("open_search_result", self.open_search_result)
        executor.register("open_app", self.open_app)
        executor.register("open_url", self.open_url)
        executor.register("open_path", self.open_path)
