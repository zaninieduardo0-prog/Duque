from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from brain.agent_state import AgentContext
from brain.autonomous_loop import AutonomousLoop
from brain.model import ModelAdapter
from brain.tool_schema import ToolSchemaRegistry, ToolSpec
from computer.workspace import Workspace
from core.executor import Executor
from core.tasks import TaskManager

from .quality import SKIP_DIRS, QualityGate

DEVELOPER_SYSTEM = (
    "Você é o engenheiro de software do Duque, trabalhando na Forja: uma cópia isolada do próprio "
    "código do Duque. Nada do que você fizer aqui afeta o Duque em execução até passar pelos testes, "
    "pelo CI e pelo merge. Trabalhe de forma autônoma, uma ação por ciclo. "
    "Retorne SOMENTE JSON válido: "
    '{"action":"tool","tool":"nome","arguments":{},"reason":"..."} ou '
    '{"action":"finish","message":"resumo do que mudou e como foi verificado"}. '
    "Regras: (1) entenda antes de mudar: liste, procure (search_code) e leia os arquivos relevantes; "
    "(2) prefira edit_file com trechos exatos a reescrever arquivos inteiros; "
    "(3) preserve o que funciona, evite duplicação e mudanças fora do objetivo; "
    "(4) toda mudança de comportamento precisa de teste em tests/ (unittest ou pytest); "
    "(5) rode run_checks e corrija até passar; nunca apague ou enfraqueça testes para fazê-los passar; "
    "(6) revise show_diff antes de concluir; (7) só finalize com evidência real de que os checks passaram. "
    "Não altere core/security.py, forge/, .github/ ou o supervisor a menos que o objetivo peça explicitamente."
)


@dataclass(slots=True)
class DevelopmentResult:
    success: bool
    message: str
    steps: int
    error: str | None = None


class SandboxTools:
    """Ferramentas do agente programador, todas presas ao diretório da Forja."""

    def __init__(self, root: Path, gate: QualityGate, diff: Callable[[], str]) -> None:
        self.workspace = Workspace(root)
        self.gate = gate
        self._diff = diff

    def list_files(self, path: str = ".") -> dict[str, Any]:
        base = self.workspace.resolve(path)
        files: list[str] = []
        for item in sorted(base.rglob("*")):
            relative = item.relative_to(self.workspace.root)
            if item.is_file() and not (set(relative.parts) & SKIP_DIRS) and relative.parts[0] != ".git":
                files.append(relative.as_posix())
        return {"files": files[:500], "total": len(files)}

    def read_file(self, path: str) -> dict[str, Any]:
        result = self.workspace.read(path)
        lines = (result.content or "").splitlines()
        numbered = "\n".join(f"{index:>4}| {line}" for index, line in enumerate(lines, 1))
        return {"path": path, "lines": len(lines), "content": numbered[:60000]}

    def read_many_files(self, paths: list[str]) -> dict[str, Any]:
        return {path: self.read_file(path)["content"] for path in paths[:12]}

    def write_file(self, path: str, content: str) -> dict[str, Any]:
        result = self.workspace.write(path, content)
        return {"path": path, "created": result.created, "changed": result.changed}

    def edit_file(self, path: str, old: str, new: str) -> dict[str, Any]:
        current = self.workspace.read(path).content or ""
        count = current.count(old)
        if count != 1:
            return {"success": False, "error": f"o trecho 'old' aparece {count} vez(es) em {path}; precisa ser único e exato"}
        self.workspace.write(path, current.replace(old, new, 1))
        return {"path": path, "changed": old != new}

    def delete_file(self, path: str) -> dict[str, Any]:
        self.workspace.delete(path)
        return {"path": path, "deleted": True}

    def search_code(self, pattern: str, path: str = ".") -> dict[str, Any]:
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return {"success": False, "error": f"regex inválida: {exc}"}
        matches: list[str] = []
        for file in self.list_files(path)["files"]:
            if not file.endswith((".py", ".md", ".toml", ".yml", ".yaml", ".html", ".txt", ".json")):
                continue
            text = (self.workspace.root / file).read_text(encoding="utf-8", errors="replace")
            for number, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    matches.append(f"{file}:{number}: {line.strip()[:200]}")
                    if len(matches) >= 200:
                        return {"pattern": pattern, "matches": matches, "truncated": True}
        return {"pattern": pattern, "matches": matches}

    def run_checks(self) -> dict[str, Any]:
        result = self.gate.run(self.workspace.root)
        return {
            "success": result.passed,
            "summary": result.summary(),
            "stdout": result.summary(),
            "error": None if result.passed else result.failure_report(),
        }

    def show_diff(self) -> dict[str, Any]:
        return {"diff": self._diff() or "(sem alterações)"}

    def register(self, executor: Executor, schemas: ToolSchemaRegistry) -> None:
        specs = [
            (ToolSpec("list_files", "Lista arquivos do projeto", (), {"path": str}), self.list_files),
            (ToolSpec("read_file", "Lê um arquivo com números de linha", ("path",), {"path": str}), self.read_file),
            (ToolSpec("read_many_files", "Lê até 12 arquivos de uma vez", ("paths",), {"paths": list}), self.read_many_files),
            (ToolSpec("search_code", "Procura uma regex nos arquivos do projeto", ("pattern",), {"pattern": str, "path": str}), self.search_code),
            (ToolSpec("edit_file", "Substitui um trecho exato e único de um arquivo", ("path", "old", "new"), {"path": str, "old": str, "new": str}), self.edit_file),
            (ToolSpec("write_file", "Cria ou reescreve um arquivo inteiro", ("path", "content"), {"path": str, "content": str}), self.write_file),
            (ToolSpec("delete_file", "Exclui um arquivo", ("path",), {"path": str}), self.delete_file),
            (ToolSpec("run_checks", "Roda compilação, testes e lint na cópia da Forja"), self.run_checks),
            (ToolSpec("show_diff", "Mostra o diff de tudo que foi alterado"), self.show_diff),
        ]
        for spec, function in specs:
            executor.register(spec.name, function)
            schemas.register(spec)


class Developer:
    """Agente programador: reutiliza o AutonomousLoop com ferramentas da Forja."""

    def __init__(self, model: ModelAdapter, tasks: TaskManager, *, max_steps: int = 80, event_sink: Callable[..., Any] | None = None) -> None:
        self.model = model
        self.tasks = tasks
        self.max_steps = max_steps
        self.event_sink = event_sink

    def develop(self, goal: str, tools: SandboxTools, feedback: str | None = None) -> DevelopmentResult:
        executor = Executor(self.tasks)
        schemas = ToolSchemaRegistry()
        tools.register(executor, schemas)
        loop = AutonomousLoop(
            self.model,
            executor,
            schemas,
            max_steps=self.max_steps,
            event_sink=self.event_sink,
            system=DEVELOPER_SYSTEM,
        )
        objective = goal
        if feedback:
            objective = (
                f"{goal}\n\nATENÇÃO: a rodada anterior não passou na verificação independente. "
                f"Corrija o problema abaixo sem enfraquecer testes:\n{feedback}"
            )
        task = self.tasks.create(f"[forja] {goal}"[:200], mode="forge")
        self.tasks.start(task.id)
        result = loop.run(AgentContext(goal=objective, task_id=task.id), confirmed=True)
        if result.success:
            self.tasks.complete(task.id, result.message)
        else:
            self.tasks.fail(task.id, result.error or "falha no agente programador")
        return DevelopmentResult(result.success, result.message, result.steps, result.error)
