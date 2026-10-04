from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from urllib.request import Request, urlopen

from ._proc import run_quiet
from .apps import PROCESS_NAMES, resolve_app
from .controller import ComputerController

# open_path abre documentos e pastas; programas e scripts nunca (para isso há
# open_app, com a lista de apps conhecidos, e run_command, que pede confirmação).
EXECUTABLE_SUFFIXES = frozenset({
    ".exe", ".bat", ".cmd", ".com", ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh",
    ".msi", ".msp", ".lnk", ".url", ".scr", ".hta", ".reg", ".pif", ".cpl", ".msc", ".jar", ".py", ".pyw",
    ".appref-ms", ".application", ".library-ms", ".settingcontent-ms",
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


# Texto que aparece no título da janela do navegador quando o site abriu.
SITE_TITLES = {
    "youtube": "YouTube", "gmail": "Gmail", "instagram": "Instagram", "chatgpt": "ChatGPT", "github": "GitHub",
    "whatsapp web": "WhatsApp", "netflix": "Netflix", "facebook": "Facebook",
}


def _is_executable(path: Path) -> bool:
    suffixes = [suffix.casefold() for suffix in path.suffixes]
    return bool(suffixes) and suffixes[-1] in EXECUTABLE_SUFFIXES


def _running_processes() -> set[str]:
    """Nomes (minúsculos) dos executáveis rodando agora (tasklist, sem janela)."""
    tasklist = run_quiet(["tasklist", "/FO", "CSV", "/NH"], timeout=30)
    return {
        line.split('","', 1)[0].strip('"').casefold()
        for line in tasklist.stdout.splitlines()
        if line.strip()
    }


class ComputerTools:
    """Ferramentas de computador expostas ao executor, sem shell arbitrário."""

    def __init__(self, controller: ComputerController | None = None) -> None:
        self.verify_seconds = 8.0
        self.controller = controller or ComputerController()
        self._last_search: dict[str, Any] | None = None

    def google_search(self, query: str) -> dict[str, Any]:
        """Abre a pesquisa do Google no navegador."""
        query = query.strip()
        if not query:
            raise ValueError("query não pode ser vazio")
        url = "https://www.google.com/search?q=" + quote_plus(query)
        self.controller.open_url(url)
        return {"query": query, "url": url, "opened": True, "message": f"Abri a pesquisa no Google: {query}."}

    def web_search(self, query: str) -> dict[str, Any]:
        query = query.strip()
        if not query:
            raise ValueError("query não pode ser vazio")
        results: list[dict[str, str]] = []
        try:
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
        except Exception:
            results = []
        if not results:
            # A busca sem navegador falha com frequência (bloqueio/captcha):
            # em vez de dizer "nenhum resultado", abre o Google para o Du.
            return self.google_search(query)
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
        """Abre um app uma única vez e confere se ele apareceu.

        Nunca devolve falha depois de mandar abrir: uma falha fazia o Duque
        repetir a tentativa (e abrir o app várias vezes). Se o app não estiver
        instalado, usa a versão web no Chrome do Du quando existir.
        """
        import platform
        import time

        from .apps import CHROME_NAMES, PROTOCOLS, WEB_FALLBACK, find_app_in_text, protocol_registered

        command = resolve_app(name)
        if not command:
            known = find_app_in_text(name)  # "minha calculadora" -> "calculadora"
            if known:
                name, command = known, resolve_app(known)
        if not command:
            raise ValueError(f"Aplicativo não encontrado: {name}")
        key = " ".join(name.casefold().split()).strip(" .,;!?\"'")
        windows = platform.system() == "Windows"
        result: dict[str, Any] = {"app": name, "command": command, "opened": True}

        # Sites cadastrados como app (YouTube, Gmail...) abrem no Chrome do Du.
        target = command[-1] if isinstance(command, list) and command else ""
        if isinstance(target, str) and target.startswith(("http://", "https://")):
            expect = SITE_TITLES.get(key, name)
            opener = getattr(self.controller, "open_url_verified", None)
            if callable(opener):
                seen = opener(target, expect)
            else:
                self.controller.open_url(target)
                seen = True
            if seen:
                return {**result, "url": target, "verified": True, "message": f"Abri {name} no navegador."}
            return {
                **result, "url": target, "verified": False,
                "message": f"Mandei abrir {name}, mas não vi a página aparecer no navegador. Confere o Chrome para mim?",
            }

        if key in CHROME_NAMES and windows and self.controller.open_chrome():
            return {**result, "message": "Abri o Chrome no seu perfil."}

        web = WEB_FALLBACK.get(key)
        protocol = PROTOCOLS.get(key)
        if windows and protocol and web and not protocol_registered(protocol):
            self.controller.open_url(web)
            return {
                **result, "url": web, "web": True,
                "message": f"O app do {name} não está instalado; abri a versão web no Chrome.",
            }

        processes = PROCESS_NAMES.get(key)
        if windows and processes:
            # Já aberto: traz a janela para a frente em vez de abrir uma segunda.
            try:
                running = bool(self.is_app_running(name)["running"])
            except Exception:
                running = False
            if running:
                from .windows_focus import focus_process_window

                try:
                    focused = focus_process_window(processes)
                except Exception:
                    focused = False
                return {
                    **result, "already_running": True, "verified": True,
                    "message": f"O {name} já estava aberto" + ("; trouxe para a frente." if focused else "."),
                }

        self.controller.launch(command)
        if windows and processes:
            deadline = time.monotonic() + self.verify_seconds
            while time.monotonic() < deadline:
                try:
                    if self.is_app_running(name)["running"]:
                        result["verified"] = True
                        return result
                except Exception:
                    break
                time.sleep(0.7)
            result["verified"] = False
            result["message"] = (
                f"Mandei abrir o {name}; ainda não vi a janela, mas ele pode estar carregando. "
                "Não tente abrir de novo sem o Du pedir."
            )
        return result

    def open_url(self, url: str) -> dict[str, Any]:
        if not url.startswith(("http://", "https://")):
            raise ValueError("URL deve começar com http:// ou https://")
        self.controller.open_url(url)
        return {"url": url, "opened": True}

    def close_app(self, name: str) -> dict[str, Any]:
        import platform
        import time

        from .apps import CHROME_NAMES, find_app_in_text

        normalized = name.casefold().strip()
        site = SITE_TITLES.get(normalized) or SITE_TITLES.get(find_app_in_text(normalized) or "")
        if site:
            # Site (YouTube, Gmail...): fecha SÓ a aba dele, nunca o navegador inteiro.
            from .windows_focus import close_tab

            tabs = close_tab(site)
            message = f"Fechei a aba do {site}." if tabs else f"Não encontrei aba do {site} aberta."
            return {"app": name, "closed": bool(tabs), "tabs": tabs, "message": message}
        if normalized in CHROME_NAMES and platform.system() == "Windows":
            # Fecha as janelas do Chrome, menos a da interface do TELEX.
            from .windows_focus import close_browser_windows

            count = close_browser_windows()
            return {"app": name, "closed": bool(count), "windows": count,
                    "message": f"Fechei {count} janela(s) do Chrome (a interface do TELEX ficou aberta)."}
        processes = PROCESS_NAMES.get(normalized)
        if not processes:
            raise ValueError(f"Não sei qual processo corresponde ao aplicativo: {name}")
        if platform.system() != "Windows":
            raise RuntimeError("Fechamento por processo está implementado apenas para Windows.")
        wanted = {process.casefold() for process in processes}
        was_running = sorted(wanted & _running_processes())
        if not was_running:
            return {"app": name, "closed": False, "processes": processes, "message": "Aplicativo não estava em execução."}
        for process in was_running:
            run_quiet(["taskkill", "/IM", process], timeout=30)
        # taskkill sem /F só PEDE para fechar (o app pode perguntar se quer salvar):
        # o código de saída não garante nada. Decide pelo estado real (até ~3 s).
        deadline = time.monotonic() + 3.0
        still = was_running
        while True:
            still = sorted(wanted & _running_processes())
            if not still or time.monotonic() >= deadline:
                break
            time.sleep(0.3)
        if still:
            return {
                "app": name, "closed": False, "processes": still, "still_running": True,
                "message": f"Pedi para fechar o {name}, mas ele continua aberto (talvez esteja perguntando se quer salvar).",
            }
        return {"app": name, "closed": True, "processes": was_running, "message": f"Fechei o {name}."}

    def is_app_running(self, name: str) -> dict[str, Any]:
        import platform

        normalized = name.casefold().strip()
        processes = PROCESS_NAMES.get(normalized)
        if not processes:
            raise ValueError(f"Não sei qual processo corresponde ao aplicativo: {name}")
        if platform.system() != "Windows":
            raise RuntimeError("Consulta por processo está implementada apenas para Windows.")
        running = _running_processes()
        matched = [process for process in processes if process.casefold() in running]
        return {"app": name, "running": bool(matched), "processes": matched}

    def open_path(self, path: str) -> dict[str, Any]:
        target = Path(path).expanduser()
        if not target.exists():
            raise FileNotFoundError(f"Caminho não encontrado: {target}")
        if target.is_file() and _is_executable(target):
            raise PermissionError(f"open_path não executa programas nem scripts: {target.name}")
        self.controller.open_path(target)
        return {"path": str(target), "opened": True}

    def register(self, executor: Any) -> None:
        executor.register("web_search", self.web_search)
        executor.register("google_search", self.google_search)
        executor.register("open_search_result", self.open_search_result)
        executor.register("open_app", self.open_app)
        executor.register("close_app", self.close_app)
        executor.register("is_app_running", self.is_app_running)
        executor.register("open_url", self.open_url)
        executor.register("open_path", self.open_path)
