"""Pedidos naturais de arquivo numa pasta pessoal, sem passar pelo modelo.

"crie um arquivo chamado teste.txt na área de trabalho contendo 123" e
"leia o arquivo teste.txt na área de trabalho" viram ``save_text_file`` /
``read_text_file`` (pastas reais do Windows, nome de arquivo saneado).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Instruções de controle no fim do pedido ("Não faça mais nada.") não são conteúdo.
CONTROL_TAIL = re.compile(
    r",?\s+e\s+(?:apenas|s[oó]|somente)\s+me\s+(?:confirme|informe|diga)\b|"
    r"(?:\.|;)\s*(?:pare|parar|pare por aí|pare por ai|não faça mais nada|nao faça mais nada|"
    r"não faça nenhuma outra ação|nao faça nenhuma outra acao|e me informe|e me diga)\b",
    re.IGNORECASE,
)
_FOLDER = r"(?P<folder>área de trabalho|area de trabalho|desktop|documentos|documents|downloads?)"
_NAME = r"(?:chamado\s+|de nome\s+)?[\"'“]?(?P<name>[^\"'”\s]+)[\"'”]?"
_CREATE = re.compile(
    r"\b(?:crie|criar|cria|escreva|escrever|salve|salvar)\s+(?:um|uma|o|a)?\s*arquivo\s+" + _NAME
    + r"\s+(?:na|no|em)\s+" + _FOLDER
    + r"\s+(?:contendo|com conteúdo|com conteudo|com o conteúdo|com o conteudo)\s+(?P<content>.+)$",
    re.IGNORECASE | re.DOTALL,
)
_READ = re.compile(
    r"\b(?:leia|ler|abra|verifique|verifica)\s+(?:o\s+)?(?:arquivo\s+)?" + _NAME
    + r"\s+(?:na|no|em)\s+" + _FOLDER + r"\b",
    re.IGNORECASE,
)


def clean_control_tail(text: str) -> str:
    value = CONTROL_TAIL.split((text or "").strip(), maxsplit=1)[0].strip().strip(" \"“”'")
    return value.rstrip(".").strip().strip(" \"“”'")


def _safe_filename(filename: str) -> str | None:
    value = filename.strip().strip(" \"“”'")
    if not value or value in {".", ".."} or Path(value).name != value or "/" in value or "\\" in value:
        return None
    return value


def _strip_assistant_prefix(text: str) -> str:
    # A interface pode acrescentar o nome mais de uma vez (ex.: "DuDu leia...").
    return re.sub(
        r"^(?:(?:telex|duque|du)[,!:;\s.-]*)+(?=(?:crie|criar|cria|escreva|escrever|salve|salvar|leia|ler|abra|verifique|verifica)\b)",
        "", text.strip(), count=1, flags=re.IGNORECASE,
    ).strip()


def _folder(spoken: str) -> str:
    value = spoken.casefold()
    if value in {"área de trabalho", "area de trabalho", "desktop"}:
        return "área de trabalho"
    return "downloads" if value.startswith("download") else "documentos"


def natural_file_plan(goal: str, available_tools: set[str] | None) -> Any:
    """Plano de uma etapa para criar/ler um arquivo numa pasta pessoal; None se não casar."""
    from .planner import Plan, PlanStep, StepKind

    def available(name: str) -> bool:
        return available_tools is None or name in available_tools

    text = _strip_assistant_prefix(goal)
    found = _CREATE.search(text)
    if found and available("save_text_file"):
        name = _safe_filename(found.group("name"))
        content = clean_control_tail(found.group("content"))
        if name and content:
            folder = _folder(found.group("folder"))
            arguments = {"name": name, "content": content, "folder": folder, "overwrite": True}
            return Plan(goal, [PlanStep(f"Criar {name} em {folder}", StepKind.TOOL, "save_text_file", arguments)])
    found = _READ.search(text)
    if found and available("read_text_file"):
        name = _safe_filename(found.group("name"))
        if name:
            folder = _folder(found.group("folder"))
            return Plan(goal, [PlanStep(f"Ler {name} em {folder}", StepKind.TOOL, "read_text_file", {"name_or_path": name, "folder": folder})])
    return None
