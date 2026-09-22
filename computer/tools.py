from __future__ import annotations

from pathlib import Path
from typing import Any

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
        results = parser.results[:8]
        return {"query": query, "results": results, "count": len(results)}
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
        executor.register("open_app", self.open_app)
        executor.register("open_url", self.open_url)
        executor.register("open_path", self.open_path)
