"""Regras determinísticas para pedidos naturais de arquivos."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def _clean_control_tail(text: str) -> str:
    value = (text or "").strip()
    value = re.split(
        r"(?:\.|;)\s*(?:pare|parar|pare por aí|pare por ai|não faça mais nada|nao faça mais nada|não faça nenhuma outra ação|nao faça nenhuma outra acao|e me informe|e me diga)\b",
        value, maxsplit=1, flags=re.IGNORECASE,
    )[0].strip()
    value = value.strip(" \"“”'")
    return value.rstrip(".").strip().strip(" \"“”'")


def _safe_filename(filename: str) -> str | None:
    value = filename.strip().strip(" \"“”'")
    if not value or value in {".", ".."} or Path(value).name != value or "/" in value or "\\" in value:
        return None
    return value


def _strip_assistant_prefix(text: str) -> str:
    """Remove formas comuns de chamar o assistente, inclusive 'Ducrie'/'DuDuque...' sem espaço."""
    value = text.strip()
    return re.sub(
        r"^(?:duque|du)[,!:;\s.-]*(?=(?:crie|criar|cria|escreva|escrever|salve|salvar)\b)",
        "",
        value,
        count=1,
        flags=re.IGNORECASE,
    ).strip()


def _natural_file_plan(planner: Any, goal: str, available_tools: set[str] | None):
    from .planner import Plan, PlanStep, StepKind

    text = _strip_assistant_prefix(goal)

    def available(name: str) -> bool:
        return available_tools is None or name in available_tools

    match = re.search(
        r"\b(?:crie|criar|cria|escreva|escrever|salve|salvar)\s+(?:um|uma|o|a)?\s*arquivo\s+(?:chamado\s+|de nome\s+)?[\"'“]?([^\"'”\s]+)[\"'”]?\s+(?:na|no|em)\s+(?:área de trabalho|area de trabalho|desktop)\s+(?:contendo|com conteúdo|com conteudo|com o conteúdo|com o conteudo)\s+(.+)$",
        text, flags=re.IGNORECASE | re.DOTALL,
    )
    if match:
        filename = _safe_filename(match.group(1))
        content = _clean_control_tail(match.group(2))
        if filename and content and available("write_desktop_file"):
            return Plan(goal, [PlanStep(
                f"Criar {filename} na área de trabalho", StepKind.TOOL, "write_desktop_file",
                {"filename": filename, "content": content},
            )])

    folders = {"documentos": "Documents", "documents": "Documents", "downloads": "Downloads", "download": "Downloads"}
    for spoken, folder in folders.items():
        match = re.search(
            rf"\b(?:crie|criar|cria|escreva|escrever|salve|salvar)\s+(?:um|uma|o|a)?\s*arquivo\s+(?:chamado\s+|de nome\s+)?[\"'“]?([^\"'”\s]+)[\"'”]?\s+(?:na|no|em)\s+{re.escape(spoken)}\s+(?:contendo|com conteúdo|com conteudo|com o conteúdo|com o conteudo)\s+(.+)$",
            text, flags=re.IGNORECASE | re.DOTALL,
        )
        if match and available("write_any_file"):
            filename = _safe_filename(match.group(1)); content = _clean_control_tail(match.group(2))
            if filename and content:
                path = Path.home() / folder / filename
                return Plan(goal, [PlanStep(f"Criar {filename} em {folder}",StepKind.TOOL,"write_any_file",{"path": str(path), "content": content})])

    match = re.search(
        r"\b(?:leia|ler|abra|verifique|verifica)\s+(?:o\s+)?(?:arquivo\s+)?(?:chamado\s+)?[\"'“]?([^\"'”\s]+)[\"'”]?\s+(?:na|no|em)\s+(?:área de trabalho|area de trabalho|desktop)\b",
        text, flags=re.IGNORECASE,
    )
    if match and available("read_any_file"):
        filename = _safe_filename(match.group(1))
        if filename:
            return Plan(goal, [PlanStep(f"Ler {filename} na área de trabalho",StepKind.TOOL,"read_any_file",{"path": str(Path.home() / "Desktop" / filename)})])
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
