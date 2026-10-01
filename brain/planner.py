from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


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


class Planner:
    """Planejador heurístico determinístico para ações operacionais comuns."""

    @staticmethod
    def _app_name(goal: str) -> str:
        value = goal.strip()
        lowered = value.casefold()
        # Remove o nome de chamada quando ele vier no início da frase.
        if lowered.startswith("duque,"):
            value = value[len("duque,"):].strip()
            lowered = value.casefold()
        prefixes = (
            "abrir o aplicativo ",
            "abrir aplicativo ",
            "abrir a aplicação ",
            "abrir aplicação ",
            "abrir o ",
            "abrir a ",
            "abrir ",
            "abra o aplicativo ",
            "abra aplicativo ",
            "abra o ",
            "abra a ",
            "abra ",
            "inicie o ",
            "inicie a ",
            "inicie ",
        )
        for prefix in prefixes:
            if lowered.startswith(prefix):
                return value[len(prefix):].strip().rstrip(".,!?")
        return value.rstrip(".,!?")

    def build(
        self,
        goal: str,
        intent: str = "chat",
        available_tools: set[str] | None = None,
    ) -> Plan:
        def tool_available(name: str) -> bool:
            return available_tools is None or name in available_tools

        if intent == "open_app":
            app_name = self._app_name(goal)
            if not tool_available("open_app"):
                return Plan(goal)
            return Plan(goal, [PlanStep(
                f"Abrir o aplicativo solicitado: {app_name}",
                StepKind.TOOL,
                "open_app",
                {"name": app_name},
            )])
        if intent == "search":
            if not tool_available("web_search"):
                return Plan(goal)
            return Plan(goal, [PlanStep(
                f"Pesquisar: {goal}",
                StepKind.TOOL,
                "web_search",
                {"query": goal},
            )])
        if intent == "file_operation":
            lowered = goal.casefold()
            if any(marker in lowered for marker in ("liste os arquivos", "listar os arquivos", "liste os ficheiros", "listar arquivos", "mostre os arquivos", "mostra os arquivos")):
                if tool_available("list_files"):
                    return Plan(goal, [PlanStep("Listar os arquivos do workspace", StepKind.TOOL, "list_files", {})])
                if tool_available("inspect_workspace"):
                    return Plan(goal, [PlanStep("Inspecionar o workspace", StepKind.TOOL, "inspect_workspace", {})])
            for marker_text in ("leia o arquivo ", "ler o arquivo ", "abra o arquivo "):
                if marker_text in lowered:
                    path = goal[lowered.index(marker_text) + len(marker_text):].strip()
                    if tool_available("read_file") and path:
                        return Plan(goal, [PlanStep(
                            f"Ler o arquivo solicitado: {path}",
                            StepKind.TOOL,
                            "read_file",
                            {"path": path},
                        )])
            for marker_text in ("apague o arquivo ", "delete o arquivo ", "exclua o arquivo "):
                if marker_text in lowered:
                    path = goal[lowered.index(marker_text) + len(marker_text):].strip()
                    if tool_available("delete_file") and path:
                        return Plan(goal, [PlanStep(
                            f"Excluir o arquivo solicitado: {path}",
                            StepKind.TOOL,
                            "delete_file",
                            {"path": path},
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
                                StepKind.TOOL,
                                "write_file",
                                {"path": path, "content": content},
                            )])
            return Plan(goal)

        if intent == "code":
            steps = [PlanStep("Entender o objetivo e os requisitos", StepKind.THINK)]
            if tool_available("list_files"):
                steps.append(PlanStep("Listar o workspace antes da alteração", StepKind.TOOL, "list_files"))
            steps.extend([
                PlanStep("Escrever ou modificar o código", StepKind.THINK),
                PlanStep("Executar o código ou teste solicitado", StepKind.THINK),
                PlanStep("Relatar o resultado", StepKind.RESPOND),
            ])
            return Plan(goal, steps)
        if intent in {"reminder", "system"}:
            return Plan(goal)
        return Plan(goal, [PlanStep("Responder à solicitação", StepKind.RESPOND)])
