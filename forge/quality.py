from __future__ import annotations

from core.windows import console_python

import importlib.util
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

SKIP_DIRS = {".git", ".venv", "venv", "duque_data", "lixeira", "__pycache__", "node_modules", "interface"}


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
    """Verificação independente do modelo: só a realidade decide se passou."""

    def __init__(self, checks: tuple[str, ...] = ("compile", "pytest", "ruff"), timeout: int = 900) -> None:
        self.checks = checks
        self.timeout = timeout

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
        return self._run("compile", [console_python(), "-m", "compileall", "-q", *targets], root)

    def _check_pytest(self, root: Path) -> CheckResult:
        if not (root / "tests").is_dir():
            return CheckResult("pytest", "failed", "pasta tests/ ausente: toda mudança precisa de testes")
        if importlib.util.find_spec("pytest") is None:
            return self._run("pytest", [console_python(), "-m", "unittest", "discover", "-s", "tests", "-t", "."], root)
        return self._run("pytest", [console_python(), "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"], root)

    def _check_ruff(self, root: Path) -> CheckResult:
        command = self._tool_command("ruff")
        if command is None:
            return CheckResult("ruff", "skipped", "ruff não instalado")
        targets = python_targets(root)
        return self._run("ruff", [*command, "check", *targets, "--select", "E,F", "--ignore", "E501"], root)

    def _check_pyright(self, root: Path) -> CheckResult:
        command = self._tool_command("pyright")
        if command is None:
            return CheckResult("pyright", "skipped", "pyright não instalado")
        return self._run("pyright", command, root)

    # utilitários -----------------------------------------------------------
    @staticmethod
    def _tool_command(name: str) -> list[str] | None:
        if importlib.util.find_spec(name) is not None:
            return [console_python(), "-m", name]
        found = shutil.which(name)
        return [found] if found else None

    def _run(self, name: str, command: list[str], root: Path) -> CheckResult:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            completed = subprocess.run(
                command,
                cwd=str(root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                env=env,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            return CheckResult(name, "failed", f"tempo limite de {self.timeout}s excedido")
        output = (completed.stdout + "\n" + completed.stderr).strip()
        return CheckResult(name, "passed" if completed.returncode == 0 else "failed", output[-4000:])
