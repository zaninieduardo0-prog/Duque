from __future__ import annotations

import platform
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from urllib.request import Request, urlopen

from ._proc import CONSOLE_ENCODING, run_quiet
from .apps import PROCESS_NAMES, normalize_app_name, resolve_app
from .controller import ComputerController, ShellTarget

# open_path abre documentos e pastas; programas e scripts exigem ferramentas
# próprias (open_app/run_command) com o nível de risco adequado.
EXECUTABLE_SUFFIXES = frozenset({
    ".exe", ".bat", ".cmd", ".com", ".ps1", ".vbs", ".vbe", ".js", ".jse",
    ".wsf", ".msi", ".lnk", ".scr", ".hta", ".reg",
})


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
        self._last_search: dict[str, Any] | None = None

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
        if self._processes_for(name, required=False) and platform.system() == "Windows":
            if self.is_app_running(name)["running"]:
                return {
                    "app": name,
                    "opened": False,
                    "already_running": True,
                    "message": f"O aplicativo {name} já está aberto.",
                }
        # Erros de inicialização (programa ausente, protocolo sem handler) sobem.
        self.controller.launch(command)
        printable = command.target if isinstance(command, ShellTarget) else command
        return {"app": name, "command": printable, "opened": True}

    def open_url(self, url: str) -> dict[str, Any]:
        if not url.startswith(("http://", "https://")):
            raise ValueError("URL deve começar com http:// ou https://")
        self.controller.open_url(url)
        return {"url": url, "opened": True}

    @staticmethod
    def _processes_for(name: str, *, required: bool = True) -> list[str]:
        processes = PROCESS_NAMES.get(normalize_app_name(name), [])
        if not processes and required:
            raise ValueError(f"Não sei qual processo corresponde ao aplicativo: {name}")
        return processes

    @staticmethod
    def _running_processes() -> set[str]:
        tasklist = run_quiet(["tasklist", "/FO", "CSV", "/NH"], timeout=30, encoding=CONSOLE_ENCODING)
        return {
            line.split('","', 1)[0].strip('"').casefold()
            for line in tasklist.stdout.splitlines()
            if line.strip()
        }

    def close_app(self, name: str) -> dict[str, Any]:
        processes = self._processes_for(name)
        if platform.system() != "Windows":
            raise RuntimeError("Fechamento por processo está implementado apenas para Windows.")
        wanted = {process.casefold() for process in processes}
        was_running = sorted(wanted & self._running_processes())
        if not was_running:
            return {"app": name, "closed": False, "processes": processes, "message": "Aplicativo não estava em execução."}
        for process in was_running:
            run_quiet(["taskkill", "/IM", process], timeout=30, encoding=CONSOLE_ENCODING)
        # taskkill sem /F pede o fechamento; o código de saída não garante que o
        # processo terminou. Decide pelo estado real, aguardando até ~3s.
        still_running = was_running
        deadline = time.monotonic() + 3.0
        while True:
            still_running = sorted(wanted & self._running_processes())
            if not still_running or time.monotonic() >= deadline:
                break
            time.sleep(0.25)
        if still_running:
            return {
                "app": name,
                "closed": False,
                "processes": still_running,
                "still_running": True,
                "message": "O aplicativo continua aberto (talvez esteja pedindo para salvar).",
            }
        return {"app": name, "closed": True, "processes": was_running}

    def is_app_running(self, name: str) -> dict[str, Any]:
        processes = self._processes_for(name)
        if platform.system() != "Windows":
            raise RuntimeError("Consulta por processo está implementada apenas para Windows.")
        running = self._running_processes()
        matched = [process for process in processes if process.casefold() in running]
        return {"app": name, "running": bool(matched), "processes": matched}

    def open_path(self, path: str) -> dict[str, Any]:
        target = Path(path).expanduser()
        if not target.exists():
            raise FileNotFoundError(f"Caminho não encontrado: {target}")
        if target.is_file() and target.suffix.casefold() in EXECUTABLE_SUFFIXES:
            raise PermissionError(f"open_path não executa programas ou scripts: {target.name}")
        self.controller.open_path(target)
        return {"path": str(target), "opened": True}

    def register(self, executor: Any) -> None:
        executor.register("web_search", self.web_search)
        executor.register("open_search_result", self.open_search_result)
        executor.register("open_app", self.open_app)
        executor.register("close_app", self.close_app)
        executor.register("is_app_running", self.is_app_running)
        executor.register("open_url", self.open_url)
        executor.register("open_path", self.open_path)
