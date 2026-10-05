from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from computer.apps import find_app_in_text
from .natural_language_patch import _natural_file_plan

_UNITS = {"segundo": 1, "segundos": 1, "minuto": 60, "minutos": 60, "hora": 3600, "horas": 3600}
_DURATION = re.compile(r"(\d+(?:[.,]\d+)?)\s*(segundos?|minutos?|horas?)")


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


# Pedido de mensagem no WhatsApp: verbo de envio/escrita + mensagem/WhatsApp, ou "procure X no WhatsApp ... mande".
from computer.whatsapp_flow import MESSAGE_REQUEST as WHATSAPP_ACTION  # noqa: E402


class Planner:
    """Planejador heurístico determinístico para ações operacionais comuns."""

    @staticmethod
    def _app_name(goal: str) -> str:
        value = goal.strip()
        lowered = value.casefold()
        if lowered.startswith("duque,"):
            value = value[len("duque,"):].strip()
            lowered = value.casefold()
        prefixes = (
            "abrir o aplicativo ", "abrir aplicativo ", "abrir a aplicação ",
            "abrir aplicação ", "abrir o ", "abrir a ", "abrir ",
            "abra o aplicativo ", "abra aplicativo ", "abra o ", "abra a ",
            "abra ", "abre o aplicativo ", "abre aplicativo ", "abre o ", "abre a ",
            "abre ", "inicie o ", "inicie a ", "inicie ",
        )
        for prefix in prefixes:
            if lowered.startswith(prefix):
                return value[len(prefix):].strip().rstrip(".,!?")
        return value.rstrip(".,!?")

    @staticmethod
    def _extract_path(goal: str, markers: tuple[str, ...]) -> str:
        lowered = goal.casefold()
        for marker in markers:
            index = lowered.find(marker)
            if index >= 0:
                return goal[index + len(marker):].strip().rstrip(".,!?")
        return ""

    def build(
        self,
        goal: str,
        intent: str = "chat",
        available_tools: set[str] | None = None,
        context_app: str | None = None,
    ) -> Plan:
        def tool_available(name: str) -> bool:
            return available_tools is None or name in available_tools

        if intent == "open_app":
            app_name = find_app_in_text(goal) or ""
            if not app_name and context_app and re.search(r"\b(?:novamente|de novo|outra vez|ele|ela|isso)\b", goal.casefold()):
                app_name = context_app
            app_name = app_name or self._app_name(goal)
            if not tool_available("open_app"):
                return Plan(goal)
            return Plan(goal, [PlanStep(
                f"Abrir o aplicativo solicitado: {app_name}",
                StepKind.TOOL, "open_app", {"name": app_name},
            )])

        if intent == "close_app":
            lowered = goal.casefold()
            names = (
                ("chrome", "chrome"), ("navegador", "chrome"), ("browser", "chrome"),
                ("edge", "edge"), ("whatsapp", "whatsapp"),
                ("bloco de notas", "bloco de notas"), ("notepad", "notepad"),
                ("calculadora", "calculadora"), ("paint", "paint"),
            )
            app_name = next((name for marker_text, name in names if marker_text in lowered), "")
            if not app_name:
                app_name = find_app_in_text(goal) or self._app_name(goal)
            if not tool_available("close_app"):
                return Plan(goal)
            return Plan(goal, [PlanStep(
                f"Fechar o aplicativo solicitado: {app_name}",
                StepKind.TOOL, "close_app", {"name": app_name},
            )])

        if intent == "check_app":
            lowered = goal.casefold()
            names = (
                ("chrome", "chrome"), ("navegador", "chrome"),
                ("edge", "edge"), ("whatsapp", "whatsapp"),
                ("bloco de notas", "bloco de notas"), ("notepad", "notepad"),
                ("calculadora", "calculadora"), ("paint", "paint"),
            )
            app_name = next((name for marker_text, name in names if marker_text in lowered), "")
            if not app_name:
                app_name = find_app_in_text(goal) or context_app or self._app_name(goal)
            if not tool_available("is_app_running"):
                return Plan(goal)
            return Plan(goal, [PlanStep(
                f"Verificar se o aplicativo está em execução: {app_name}",
                StepKind.TOOL, "is_app_running", {"name": app_name},
            )])

        if intent == "open_search_result":
            if not tool_available("open_search_result"):
                return Plan(goal)
            lowered = goal.casefold()
            index = 1
            for marker in ("resultado ", "resultado número ", "resultado numero "):
                position = lowered.find(marker)
                if position >= 0:
                    remainder = goal[position + len(marker):].strip()
                    digits = ""
                    for char in remainder:
                        if char.isdigit():
                            digits += char
                        else:
                            break
                    if digits:
                        index = int(digits)
                    break
            return Plan(goal, [PlanStep(
                f"Abrir o resultado de pesquisa {index}",
                StepKind.TOOL, "open_search_result", {"index": index},
            )])

        if intent == "search":
            query = self.search_query(goal)
            lowered = goal.casefold()
            wants_browser = any(word in lowered for word in ("google", "navegador", "página", "pagina", "chrome", "abra", "abre", "abrir"))
            tool = "google_search" if wants_browser and tool_available("google_search") else "web_search"
            if not tool_available(tool):
                return Plan(goal)
            return Plan(goal, [PlanStep(f"Pesquisar: {query}", StepKind.TOOL, tool, {"query": query})])

        if intent == "file_operation":
            # Casos naturais precisam ser resolvidos antes das regras antigas.
            # Isso evita depender de uma inicialização implícita via sitecustomize.
            natural_plan = _natural_file_plan(self, goal, available_tools)
            if natural_plan is not None:
                return natural_plan

            lowered = goal.casefold()
            folder_plan = self._folder_or_search_plan(goal, tool_available)
            if folder_plan is not None:
                return folder_plan
            if any(marker in lowered for marker in (
                "liste os arquivos", "listar os arquivos", "liste os ficheiros",
                "listar arquivos", "mostre os arquivos", "mostra os arquivos",
                "mostre os ficheiros", "listar a pasta", "mostre a pasta",
            )):
                if tool_available("list_files"):
                    return Plan(goal, [PlanStep(
                        "Listar os arquivos do workspace", StepKind.TOOL, "list_files", {}
                    )])
                if tool_available("inspect_workspace"):
                    return Plan(goal, [PlanStep(
                        "Inspecionar o workspace", StepKind.TOOL, "inspect_workspace", {}
                    )])

            path = self._extract_path(goal, (
                "leia o arquivo ", "ler o arquivo ", "abra o arquivo ",
                "leia arquivo ", "ler arquivo ", "abra arquivo ",
                "analise o arquivo ", "analisa o arquivo ",
                "analise arquivo ", "analisa arquivo ",
                "mostre o conteúdo de ", "mostre o conteudo de ",
            ))
            if path and tool_available("read_file"):
                return Plan(goal, [PlanStep(
                    f"Ler o arquivo solicitado: {path}",
                    StepKind.TOOL, "read_file", {"path": path},
                )])

            if any(marker in lowered for marker in (
                "analise o projeto", "analisa o projeto", "verifique o projeto",
                "verifica o projeto", "inspecione o projeto", "inspeciona o projeto",
                "estrutura do projeto", "estrutura do repositório",
            )):
                if tool_available("inspect_workspace"):
                    return Plan(goal, [PlanStep(
                        "Inspecionar o workspace", StepKind.TOOL, "inspect_workspace", {}
                    )])

            path = self._extract_path(goal, (
                "apague o arquivo ", "delete o arquivo ", "exclua o arquivo ",
                "apague arquivo ", "delete arquivo ", "exclua arquivo ",
            ))
            if path and tool_available("delete_file"):
                return Plan(goal, [PlanStep(
                    f"Excluir o arquivo solicitado: {path}",
                    StepKind.TOOL, "delete_file", {"path": path},
                )])

            for marker_text in ("crie o arquivo ", "criar o arquivo ", "escreva o arquivo ", "salve o arquivo "):
                if marker_text in lowered and tool_available("write_file"):
                    remainder = goal[lowered.index(marker_text) + len(marker_text):].strip()
                    separator = " com conteúdo "
                    if separator in remainder.casefold():
                        split_at = remainder.casefold().index(separator)
                        path = remainder[:split_at].strip()
                        content = remainder[split_at + len(separator):]
                        if path and content:
                            return Plan(goal, [PlanStep(
                                f"Criar o arquivo solicitado: {path}",
                                StepKind.TOOL, "write_file",
                                {"path": path, "content": content},
                            )])
            return Plan(goal)

        if intent == "code":
            steps = [PlanStep("Entender o objetivo e os requisitos", StepKind.THINK)]
            if tool_available("list_files"):
                steps.append(PlanStep("Listar o workspace antes da alteração", StepKind.TOOL, "list_files"))
            steps.extend([
                PlanStep("Escrever ou modificar o código", StepKind.THINK),
                PlanStep("Executar a verificação disponível", StepKind.THINK),
                PlanStep("Relatar o resultado", StepKind.RESPOND),
            ])
            return Plan(goal, steps)

        assistant_plan = self._assistant_plan(goal, intent, tool_available)
        if assistant_plan is not None:
            return assistant_plan

        if intent in {"reminder", "system"}:
            return Plan(goal)

        return Plan(goal, [PlanStep("Responder à solicitação", StepKind.RESPOND)])

    @staticmethod
    def search_query(goal: str) -> str:
        text = goal.strip()
        match = re.search(r"\b(?:pesquis[ae]r?|procur[ae]r?|busc[ae]r?)\b\s*(?:no google|na internet|na web|sobre|por)?\s*[:,]?\s*(.+)$", text, flags=re.IGNORECASE)
        if match:
            text = match.group(1)
        text = re.sub(r"\s*(?:no google|na internet|na web|no navegador|por aqui mesmo)\s*", " ", text, flags=re.IGNORECASE)
        return text.strip(" .,!?") or goal.strip()

    @staticmethod
    def parse_duration(text: str) -> float | None:
        """Soma durações como "1 hora e 30 minutos" em segundos."""
        total = 0.0
        for value, unit in _DURATION.findall(text.casefold()):
            total += float(value.replace(",", ".")) * _UNITS[unit]
        return total or None
