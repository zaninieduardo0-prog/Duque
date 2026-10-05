"""Compatibilidade de linguagem natural para o Planner e o Bloco de Notas.

Mantém as regras determinísticas principais do projeto intactas, mas cobre
formas naturais de pedir operações de arquivo e impede que instruções de
controle da tarefa virem conteúdo a ser digitado.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def _clean_control_tail(text: str) -> str:
    value = (text or "").strip()
    # O texto pedido termina antes de instruções de controle da tarefa.
    value = re.split(
        r"(?:\.|;)\s*(?:pare|parar|pare por aí|pare por ai|não faça mais nada|"
        r"nao faça mais nada|não faça nenhuma outra ação|nao faça nenhuma outra acao|"
        r"e me informe|e me diga)\b",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    return value.strip(" \"“”'")


def _natural_file_plan(planner: Any, goal: str, available_tools: set[str] | None):
    """Retorna um Plan para pedidos de arquivo em linguagem natural."""
    from .planner import Plan, PlanStep, StepKind

    text = goal.strip()
    lowered = " ".join(text.casefold().split())

    def available(name: str) -> bool:
        return available_tools is None or name in available_tools

    # criar/escrever arquivo na área de trabalho/desktop
    match = re.search(
        r"\b(?:crie|criar|cria|escreva|escrever|salve|salvar)\s+"
        r"(?:um|uma|o|a)?\s*arquivo\s+(?:chamado\s+|de nome\s+)?"
        r"[\"'“]?([^\"'”\s]+)[\"'”]?\s+"
        r"(?:na|no|em)\s+(?:área de trabalho|area de trabalho|desktop)\s+"
        r"(?:contendo|com conteúdo|com conteudo|com o conteúdo|com o conteudo)\s+(.+)$",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match:
        filename = match.group(1).strip()
        content = _clean_control_tail(match.group(2))
        if filename and content and available("write_any_file"):
            path = Path.home() / "Desktop" / filename
            return Plan(
                goal,
                [PlanStep(
                    f"Criar {filename} na área de trabalho",
                    StepKind.TOOL,
                    "write_any_file",
                    {"path": str(path), "content": content},
                )],
            )

    # criar/escrever arquivo em uma pasta conhecida.
    folders = {
        "documentos": "Documents",
        "documents": "Documents",
        "downloads": "Downloads",
        "download": "Downloads",
        "área de trabalho": "Desktop",
        "area de trabalho": "Desktop",
        "desktop": "Desktop",
    }
    for spoken, folder in sorted(folders.items(), key=lambda item: len(item[0]), reverse=True):
        match = re.search(
            rf"\b(?:crie|criar|cria|escreva|escrever|salve|salvar)\s+"
            rf"(?:um|uma|o|a)?\s*arquivo\s+(?:chamado\s+|de nome\s+)?"
            rf"[\"'“]?([^\"'”\s]+)[\"'”]?\s+(?:na|no|em)\s+"
            rf"{re.escape(spoken)}\s+(?:contendo|com conteúdo|com conteudo|com o conteúdo|com o conteudo)\s+(.+)$",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match and available("write_any_file"):
            filename = match.group(1).strip()
            content = _clean_control_tail(match.group(2))
            if filename and content:
                path = Path.home() / folder / filename
                return Plan(
                    goal,
                    [PlanStep(
                        f"Criar {filename} em {folder}",
                        StepKind.TOOL,
                        "write_any_file",
                        {"path": str(path), "content": content},
                    )],
                )

    # leitura/verificação de arquivo na área de trabalho.
    match = re.search(
        r"\b(?:leia|ler|leia o|ler o|abra|abra o|verifique|verifica)\s+"
        r"(?:arquivo\s+)?(?:chamado\s+)?[\"'“]?([^\"'”\s]+)[\"'”]?\s+"
        r"(?:na|no|em)\s+(?:área de trabalho|area de trabalho|desktop)\b",
        text,
        flags=re.IGNORECASE,
    )
    if match and available("read_any_file"):
        filename = match.group(1).strip()
        path = Path.home() / "Desktop" / filename
        return Plan(
            goal,
            [PlanStep(
                f"Ler {filename} na área de trabalho",
                StepKind.TOOL,
                "read_any_file",
                {"path": str(path)},
            )],
        )

    return None


def install() -> None:
    from .planner import Planner

    if getattr(Planner, "_duque_natural_patch", False):
        return

    original_build = Planner.build
    original_notepad = Planner._notepad_request

    def build(self, goal, intent="chat", available_tools=None, context_app=None):
        if intent == "file_operation":
            plan = _natural_file_plan(self, goal, available_tools)
            if plan is not None:
                return plan
        return original_build(self, goal, intent, available_tools, context_app)

    @staticmethod
    def notepad_request(goal: str):
        return original_notepad(_clean_control_tail(goal))

    Planner.build = build
    Planner._notepad_request = notepad_request
    Planner._duque_natural_patch = True
