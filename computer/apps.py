from __future__ import annotations

import shutil


# Comandos conhecidos e deliberadamente explícitos. Novos aplicativos podem ser
# cadastrados aqui sem permitir que o modelo execute uma string arbitrária.
KNOWN_APPS: dict[str, list[str]] = {
    "notepad": ["notepad.exe"],
    "bloco de notas": ["notepad.exe"],
}


def resolve_app(name: str) -> list[str] | None:
    normalized = name.casefold().strip()
    if normalized in KNOWN_APPS:
        return KNOWN_APPS[normalized]
    executable = shutil.which(name)
    return [executable] if executable else None
