from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from computer.apps import PROCESS_NAMES

from .router import _CLOSE, _OPEN, _SEARCH, normalize


class StepKind(str, Enum):
    THINK = "think"
    TOOL = "tool"
    RESPOND = "respond"


@dataclass(slots=True)
class PlanStep:
    description: str
    kind: StepKind = StepKind.THINK
    tool: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Plan:
    goal: str
    steps: list[PlanStep] = field(default_factory=list)
    # Resposta direta quando o pedido é só conversa (preenchida pelo modelo).
    answer: str | None = None


_ORDINALS = {
    "primeiro": 1, "segundo": 2, "terceiro": 3, "quarto": 4,
    "quinto": 5, "sexto": 6, "sétimo": 7, "setimo": 7, "oitavo": 8,
}


def _clean(value: str) -> str:
    return value.strip().strip(" .,!?\"'")


class Planner:
    """Planejador heurístico determinístico para os comandos que o roteador reconhece."""

    @staticmethod
    def _app_name(goal: str) -> str:
        command = normalize(goal)
        for pattern in (_OPEN, _CLOSE):
            match = pattern.match(command)
            if match:
                return _clean(match.group("app"))
        return _clean(command)

    @staticmethod
    def _mentioned_app(goal: str) -> str:
        value = normalize(goal)
        # O nome mais longo primeiro: "google chrome" antes de "chrome".
        for app in sorted(PROCESS_NAMES, key=len, reverse=True):
            if re.search(rf"\b{re.escape(app)}\b", value):
                return app
        return ""

    @staticmethod
    def _result_index(goal: str) -> int:
        value = normalize(goal)
        match = re.search(r"resultado\s+(?:n[úu]mero\s+)?(\d+)", value) or re.search(r"(\d+)º?\s+resultado", value)
        if match:
            return int(match.group(1))
        for word, index in _ORDINALS.items():
            if re.search(rf"\b{word}\b", value):
                return index
        return 1

    @staticmethod
    def _after(goal: str, pattern: str) -> str:
        match = re.search(pattern, goal, flags=re.IGNORECASE)
        return _clean(goal[match.end():]) if match else ""

    def build(
        self,
        goal: str,
        intent: str = "chat",
        available_tools: set[str] | None = None,
        context_app: str | None = None,
    ) -> Plan:
        def tool_available(name: str) -> bool:
            return available_tools is None or name in available_tools

        def single(description: str, tool: str, arguments: dict[str, Any]) -> Plan:
            if not tool_available(tool):
                return Plan(goal)
            return Plan(goal, [PlanStep(description, StepKind.TOOL, tool, arguments)])

        if intent == "open_app":
            app_name = self._app_name(goal)
            return single(f"Abrir o aplicativo solicitado: {app_name}", "open_app", {"name": app_name})

        if intent == "close_app":
            app_name = self._mentioned_app(goal) or self._app_name(goal)
            return single(f"Fechar o aplicativo solicitado: {app_name}", "close_app", {"name": app_name})

        if intent == "check_app":
            app_name = self._mentioned_app(goal) or context_app or ""
            if not app_name:
                return Plan(goal)
            return single(f"Verificar se o aplicativo está em execução: {app_name}", "is_app_running", {"name": app_name})

        if intent == "open_search_result":
            index = self._result_index(goal)
            return single(f"Abrir o resultado de pesquisa {index}", "open_search_result", {"index": index})

        if intent == "search":
            match = _SEARCH.match(normalize(goal))
            query = _clean(match.group("query")) if match else _clean(goal)
            return single(f"Pesquisar: {query}", "web_search", {"query": query})

        if intent == "file_operation":
            return self._file_plan(goal, single)

        return Plan(goal, [PlanStep("Responder à solicitação", StepKind.RESPOND)])

    def _file_plan(self, goal: str, single) -> Plan:
        lowered = normalize(goal)
        if re.match(r"^(?:liste|listar|lista|mostre|mostra)\s+(?:os\s+)?arquivos", lowered):
            return single("Listar os arquivos do workspace", "list_files", {})

        path = self._after(goal, r"\b(?:leia|ler|l[êe])\s+o\s+arquivo\s+") or self._after(
            goal, r"\bmostr[ae]\s+o\s+conte[úu]do\s+(?:do\s+arquivo\s+|de\s+)"
        )
        if path:
            return single(f"Ler o arquivo solicitado: {path}", "read_file", {"path": path})

        path = self._after(goal, r"\b(?:apague|delete|exclua)\s+o\s+arquivo\s+")
        if path:
            return single(f"Excluir o arquivo solicitado: {path}", "delete_file", {"path": path})

        match = re.search(
            r"\b(?:crie|criar|escreva|salve)\s+o\s+arquivo\s+(?P<path>\S+)\s+com\s+conte[úu]do\s+(?P<content>.+)$",
            goal.strip(),
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            path = _clean(match.group("path"))
            return single(f"Criar o arquivo solicitado: {path}", "write_file", {"path": path, "content": match.group("content")})
        return Plan(goal)
