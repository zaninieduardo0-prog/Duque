"""Rotinas: um nome que dispara vários comandos de uma vez.

"modo trabalho" -> abre o VS Code, o Spotify e o GitHub.
"crie a rotina estudo: modo foco por 50 minutos, abre o youtube" -> salva.

As rotinas são compiladas para etapas de ferramentas (roteador + planner
determinísticos) no momento em que são criadas; assim, rodar uma rotina não
depende do modelo e o resultado é sempre o mesmo.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Callable

from memory.memory import Memory, MemoryLayer

from .planner import Planner, StepKind
from .router import IntentRouter

KEY = "rotinas"

DEFAULT_ROUTINES: dict[str, dict[str, Any]] = {
    "trabalho": {
        "commands": ["abre o vscode", "abre o spotify", "abre o github"],
        "steps": [
            {"tool": "open_app", "arguments": {"name": "vscode"}},
            {"tool": "open_app", "arguments": {"name": "spotify"}},
            {"tool": "open_app", "arguments": {"name": "github"}},
        ],
    },
    "estudo": {
        "commands": ["modo foco por 50 minutos"],
        "steps": [{"tool": "focus_mode", "arguments": {"action": "start", "minutes": 50.0}}],
    },
    "jogo": {
        "commands": ["abre o steam", "abre o discord"],
        "steps": [
            {"tool": "open_app", "arguments": {"name": "steam"}},
            {"tool": "open_app", "arguments": {"name": "discord"}},
        ],
    },
}


def normalize_name(name: str) -> str:
    folded = unicodedata.normalize("NFKD", name.casefold()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", folded).strip()


def split_commands(text: str) -> list[str]:
    parts = re.split(r"\s*(?:,|;|\be depois\b|\bdepois\b|\be\b(?=\s+(?:abr|fech|toc|coloc|pause|paus|modo|foco|aument|diminu|bloque|pesquis|procur|me lembr)))\s*", text.strip(), flags=re.IGNORECASE)
    return [part.strip(" .") for part in parts if part and part.strip(" .")]


class Routines:
    def __init__(self, memory: Memory, run_step: Callable[[str, dict[str, Any]], tuple[bool, str]], available_tools: Callable[[], set[str]]) -> None:
        self.memory = memory
        self.run_step = run_step
        self.available_tools = available_tools
        self.router = IntentRouter()
        self.planner = Planner()

    # armazenamento -----------------------------------------------------------
    def _load(self) -> dict[str, dict[str, Any]]:
        stored = self.memory.recall(MemoryLayer.PERSONAL, KEY, None)
        if not isinstance(stored, dict):
            return {name: dict(value) for name, value in DEFAULT_ROUTINES.items()}
        return stored

    def _store(self, routines: dict[str, dict[str, Any]]) -> None:
        self.memory.remember(MemoryLayer.PERSONAL, KEY, routines)

    # compilação --------------------------------------------------------------
    def compile(self, commands: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
        steps: list[dict[str, Any]] = []
        unknown: list[str] = []
        tools = self.available_tools()
        for command in commands:
            route = self.router.route(command)
            plan = self.planner.build(command, route.intent.value, tools)
            tool_steps = [step for step in plan.steps if step.kind == StepKind.TOOL and step.tool]
            if not tool_steps:
                unknown.append(command)
                continue
            steps.extend({"tool": step.tool, "arguments": dict(step.arguments)} for step in tool_steps)
        return steps, unknown

    # ferramentas -------------------------------------------------------------
    def routine_save(self, name: str, commands: str) -> dict[str, Any]:
        key = normalize_name(name)
        if not key:
            return {"success": False, "error": "A rotina precisa de um nome."}
        parts = split_commands(commands)
        steps, unknown = self.compile(parts)
        if not steps:
            return {"success": False, "error": "Não reconheci nenhum comando: " + "; ".join(unknown or parts)}
        routines = self._load()
        routines[key] = {"commands": parts, "steps": steps}
        self._store(routines)
        message = f"Rotina '{key}' salva com {len(steps)} ação(ões). Diga 'modo {key}' para rodar."
        if unknown:
            message += " Não entendi: " + "; ".join(unknown) + "."
        return {"message": message, "steps": steps, "unknown": unknown}

    def routine_run(self, name: str) -> dict[str, Any]:
        key = normalize_name(name)
        routines = self._load()
        routine = routines.get(key)
        if routine is None:
            names = ", ".join(sorted(routines)) or "nenhuma"
            return {"success": False, "error": f"Não conheço a rotina '{name}'. Rotinas: {names}."}
        done: list[str] = []
        failed: list[str] = []
        for step in routine.get("steps", []):
            ok, detail = self.run_step(str(step["tool"]), dict(step.get("arguments") or {}))
            (done if ok else failed).append(detail)
        if not done:
            return {"success": False, "error": f"A rotina '{key}' falhou: " + "; ".join(failed)}
        message = f"Modo {key} ativado."
        if failed:
            message += " Falharam: " + "; ".join(failed) + "."
        return {"message": message, "done": done, "failed": failed}

    def routines_list(self) -> dict[str, Any]:
        routines = self._load()
        if not routines:
            return {"message": "Nenhuma rotina salva.", "routines": {}}
        lines = [f"{name}: " + ", ".join(value.get("commands", [])) for name, value in sorted(routines.items())]
        return {"message": "Rotinas:\n" + "\n".join(lines), "routines": routines}

    def routine_delete(self, name: str) -> dict[str, Any]:
        key = normalize_name(name)
        routines = self._load()
        if key not in routines:
            return {"success": False, "error": f"Não existe a rotina '{name}'."}
        routines.pop(key)
        self._store(routines)
        return {"message": f"Apaguei a rotina '{key}'."}
