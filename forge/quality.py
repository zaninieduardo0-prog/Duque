from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .git import NO_WINDOW, quiet_env

SKIP_DIRS = {".git", ".venv", "venv", "duque_data", "lixeira", "__pycache__", "node_modules"}

# Módulos de entrada do Duque: importá-los pega dependência faltando e erro de
# inicialização que a compilação sozinha não vê.
RUNTIME_MODULES = ("servidor", "duque_wake")

# Credenciais e caminhos da instalação ao vivo nunca chegam ao código que está
# sendo verificado (testes escritos pelo agente rodam com este ambiente).
_SECRET_ENV = re.compile(r"(_API_KEY|_TOKEN|_SECRET|_PASSWORD)$", re.IGNORECASE)
_STRIPPED_ENV = {"GITHUB_TOKEN", "DUQUE_WORKSPACE_ROOT", "DUQUE_FORGE_DIR"}


def sandbox_env(root: Path, base: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        key: value
        for key, value in quiet_env(base).items()
        if key.upper() not in _STRIPPED_ENV and not _SECRET_ENV.search(key)
    }
    env["DUQUE_WORKSPACE_ROOT"] = str(root)
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


@dataclass(slots=True)
class CheckResult:
    name: str
    status: str  # passed | failed | skipped
    output: str = ""

    @property
    def failed(self) -> bool:
        return self.status == "failed"


@dataclass(slots=True)
class GateResult:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.checks) and not any(check.failed for check in self.checks)

    def summary(self) -> str:
        return ", ".join(f"{check.name}: {check.status}" for check in self.checks)

    def failure_report(self, max_chars: int = 6000) -> str:
        parts = [f"## {check.name}\n{check.output}" for check in self.checks if check.failed]
        text = "\n\n".join(parts)
        return text[-max_chars:]


def python_targets(root: Path) -> list[str]:
    """Pacotes e scripts Python do projeto, sem entrar em duque_data/.venv."""
    targets: list[str] = []
    for entry in sorted(root.iterdir()):
        if entry.name in SKIP_DIRS or entry.name.startswith("."):
            continue
        if entry.is_file() and entry.suffix == ".py":
            targets.append(entry.name)
        elif entry.is_dir() and any(entry.rglob("*.py")):
            targets.append(entry.name)
    return targets


class QualityGate:
    """Verificação independente do modelo: só a realidade decide se passou.

    Com ``strict`` (usado quando o CI é obrigatório), ferramenta ausente conta
    como falha: sem pytest/ruff a verificação local não prova nada.
    """

    def __init__(
        self,
        checks: tuple[str, ...] = ("compile", "imports", "pytest", "ruff"),
        timeout: int = 900,
        *,
        strict: bool = False,
    ) -> None:
        self.checks = checks
        self.timeout = timeout
        self.strict = strict

    def run(self, root: str | Path) -> GateResult:
        root = Path(root)
        result = GateResult()
        for name in self.checks:
            runner = getattr(self, f"_check_{name}", None)
            if runner is None:
                result.checks.append(CheckResult(name, "failed", f"verificação desconhecida: {name}"))
                continue
            result.checks.append(runner(root))
        return result

    # verificações --------------------------------------------------------
    def _check_compile(self, root: Path) -> CheckResult:
        targets = python_targets(root)
        if not targets:
            return CheckResult("compile", "skipped", "nenhum arquivo Python")
        return self._run("compile", [sys.executable, "-m", "compileall", "-q", *targets], root)

    def _check_imports(self, root: Path) -> CheckResult:
        modules = [name for name in RUNTIME_MODULES if (root / f"{name}.py").is_file()]
        if not modules:
            return CheckResult("imports", "skipped", "nenhum módulo de entrada do Duque")
        code = "; ".join(f"import {name}" for name in modules)
        return self._run("imports", [sys.executable, "-c", code], root)

    def _check_pytest(self, root: Path) -> CheckResult:
        if not (root / "tests").is_dir():
            return CheckResult("pytest", "failed", "pasta tests/ ausente: toda mudança precisa de testes")
        if importlib.util.find_spec("pytest") is None:
            if self.strict:
                return CheckResult("pytest", "failed", "pytest não instalado (obrigatório quando o CI é exigido)")
            return self._run("pytest", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."], root)
        return self._run("pytest", [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"], root)

    def _check_ruff(self, root: Path) -> CheckResult:
        command = self._tool_command("ruff")
        if command is None:
            return self._missing("ruff")
        targets = python_targets(root)
        return self._run("ruff", [*command, "check", *targets, "--select", "E,F", "--ignore", "E501"], root)

    def _check_pyright(self, root: Path) -> CheckResult:
        command = self._tool_command("pyright")
        if command is None:
            return self._missing("pyright")
        return self._run("pyright", command, root)

    # utilitários -----------------------------------------------------------
    def _missing(self, name: str) -> CheckResult:
        if self.strict:
            return CheckResult(name, "failed", f"{name} não instalado (obrigatório quando o CI é exigido)")
        return CheckResult(name, "skipped", f"{name} não instalado")

    @staticmethod
    def _tool_command(name: str) -> list[str] | None:
        if importlib.util.find_spec(name) is not None:
            return [sys.executable, "-m", name]
        found = shutil.which(name)
        return [found] if found else None

    def _run(self, name: str, command: list[str], root: Path) -> CheckResult:
        try:
            completed = subprocess.run(
                command,
                cwd=str(root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                env=sandbox_env(root),
                shell=False,
                creationflags=NO_WINDOW,
            )
        except subprocess.TimeoutExpired:
            return CheckResult(name, "failed", f"tempo limite de {self.timeout}s excedido")
        except OSError as exc:
            return CheckResult(name, "failed", f"não foi possível executar: {exc}")
        output = (completed.stdout + "\n" + completed.stderr).strip()
        return CheckResult(name, "passed" if completed.returncode == 0 else "failed", output[-4000:])
