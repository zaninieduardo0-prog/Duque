from __future__ import annotations

import shutil


# Comandos conhecidos e deliberadamente explícitos. Novos aplicativos podem ser
# cadastrados aqui sem permitir que o modelo execute uma string arbitrária.
KNOWN_APPS: dict[str, list[str]] = {
    "notepad": ["notepad.exe"],
    "bloco de notas": ["notepad.exe"],
    # O protocolo whatsapp: permite abrir o aplicativo oficial instalado no
    # Windows sem depender de um caminho fixo de instalação.
    "whatsapp": ["cmd.exe", "/c", "start", "", "whatsapp:"],
    "whatsapp desktop": ["cmd.exe", "/c", "start", "", "whatsapp:"],
}

# Adiciona atalhos comuns do Windows e nomes em português
KNOWN_APPS.update({
    "calculadora": ["calc.exe"],
    "calculadora do windows": ["calc.exe"],
    "calc": ["calc.exe"],
    "explorador": ["explorer.exe"],
    "explorer": ["explorer.exe"],
    "chrome": ["cmd.exe", "/c", "start", "", "chrome"],
    "google chrome": ["cmd.exe", "/c", "start", "", "chrome"],
    "edge": ["cmd.exe", "/c", "start", "", "microsoft-edge:"] ,
    "microsoft edge": ["cmd.exe", "/c", "start", "", "microsoft-edge:"] ,
    "paint": ["mspaint.exe"],
})

PROCESS_NAMES: dict[str, list[str]] = {
    "notepad": ["notepad.exe"],
    "bloco de notas": ["notepad.exe"],
    "calculadora": ["calculatorapp.exe", "calc.exe"],
    "calculadora do windows": ["calculatorapp.exe", "calc.exe"],
    "calc": ["calculatorapp.exe", "calc.exe"],
    "explorador": ["explorer.exe"],
    "explorer": ["explorer.exe"],
    "chrome": ["chrome.exe"],
    "google chrome": ["chrome.exe"],
    "edge": ["msedge.exe"],
    "microsoft edge": ["msedge.exe"],
    "paint": ["mspaint.exe"],
    "whatsapp": ["whatsapp.exe"],
    "whatsapp desktop": ["whatsapp.exe"],
}
})


def resolve_app(name: str) -> list[str] | None:
    normalized = name.casefold().strip()
    if normalized in KNOWN_APPS:
        return KNOWN_APPS[normalized]
    executable = shutil.which(name)
    return [executable] if executable else None
