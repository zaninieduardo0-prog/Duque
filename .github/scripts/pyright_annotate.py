"""Roda o pyright e publica cada erro como anotação do GitHub Actions.

As anotações aparecem no PR e podem ser lidas pela API, o que permite que o
próprio Duque (ou um revisor) entenda a falha sem baixar o log completo.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys


def escape_data(value: str) -> str:
    """Escapa a mensagem de um comando do GitHub Actions (::error ...::mensagem)."""
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def escape_property(value: str) -> str:
    """Escapa propriedades (file=, title=), onde ':' e ',' também são separadores."""
    return escape_data(value).replace(":", "%3A").replace(",", "%2C")


completed = subprocess.run(["pyright", "--outputjson"], capture_output=True, text=True)
try:
    report = json.loads(completed.stdout)
except json.JSONDecodeError:
    print(completed.stdout)
    print(completed.stderr, file=sys.stderr)
    sys.exit(completed.returncode or 1)

root = os.getcwd()
errors = 0
for diagnostic in report.get("generalDiagnostics", []):
    severity = diagnostic.get("severity")
    if severity not in {"error", "warning"}:
        continue
    path = os.path.relpath(diagnostic.get("file", ""), root).replace("\\", "/")
    line = diagnostic.get("range", {}).get("start", {}).get("line", 0) + 1
    message = diagnostic.get("message", "")
    rule = diagnostic.get("rule", "")
    print(
        f"::{severity} file={escape_property(path)},line={line},"
        f"title={escape_property(f'pyright {rule}')}::{escape_data(message)}"
    )
    print(f"{path}:{line} {severity}: {' '.join(message.split())} ({rule})")
    errors += severity == "error"

summary = report.get("summary", {})
print(f"pyright: {summary.get('errorCount', errors)} erro(s), {summary.get('warningCount', 0)} aviso(s)")
sys.exit(1 if errors else 0)
