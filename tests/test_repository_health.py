from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def python_files() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*.py")
        if ".venv" not in path.parts and "lixeira" not in path.parts
    )


def test_python_files_have_valid_syntax() -> None:
    files = python_files()
    assert files, "Nenhum arquivo Python encontrado no repositório."

    failures: list[str] = []
    for path in files:
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError) as exc:
            failures.append(f"{path.relative_to(ROOT)}: {exc}")

    assert not failures, "Arquivos Python com sintaxe inválida:\n" + "\n".join(failures)


def test_critical_voice_files_exist() -> None:
    required = [
        ROOT / "duque_wake_v2.py",
        ROOT / "duque_wake_v3.py",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    assert not missing, "Arquivos críticos ausentes: " + ", ".join(missing)
