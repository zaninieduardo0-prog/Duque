from __future__ import annotations

from pathlib import Path
from typing import Any

from .apps import resolve_app
from .controller import ComputerController


class ComputerTools:
    """Ferramentas de computador expostas ao executor, sem shell arbitrário."""

    def __init__(self, controller: ComputerController | None = None) -> None:
        self.controller = controller or ComputerController()

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
        executor.register("open_app", self.open_app)
        executor.register("open_url", self.open_url)
        executor.register("open_path", self.open_path)
