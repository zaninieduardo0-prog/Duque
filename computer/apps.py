from __future__ import annotations

import re

from .controller import ShellTarget

AppCommand = list[str] | ShellTarget

# Comandos conhecidos e deliberadamente explícitos. Novos aplicativos podem ser
# cadastrados aqui sem permitir que o modelo execute uma string arbitrária.
# ShellTarget abre via os.startfile (protocolos como whatsapp: e App Paths como
# chrome) sem passar por cmd.exe, então nenhuma janela de console pisca.
KNOWN_APPS: dict[str, AppCommand] = {
    "notepad": ["notepad.exe"],
    "bloco de notas": ["notepad.exe"],
    # O protocolo whatsapp: permite abrir o aplicativo oficial instalado no
    # Windows sem depender de um caminho fixo de instalação.
    "whatsapp": ShellTarget("whatsapp:"),
    "whatsapp desktop": ShellTarget("whatsapp:"),
}

# Adiciona atalhos comuns do Windows e nomes em português
KNOWN_APPS.update({
    "calculadora": ["calc.exe"],
    "calculadora do windows": ["calc.exe"],
    "calc": ["calc.exe"],
    "explorador": ["explorer.exe"],
    "explorer": ["explorer.exe"],
    "navegador": ShellTarget("chrome"),
    "browser": ShellTarget("chrome"),
    "chrome": ShellTarget("chrome"),
    "google chrome": ShellTarget("chrome"),
    "edge": ShellTarget("microsoft-edge:"),
    "microsoft edge": ShellTarget("microsoft-edge:"),
    "paint": ["mspaint.exe"],
})

# explorer.exe não entra aqui: é o shell do Windows (barra de tarefas, área de
# trabalho). Fechá-lo derrubaria a interface e ele está sempre "em execução".
PROCESS_NAMES: dict[str, list[str]] = {
    "notepad": ["notepad.exe"],
    "bloco de notas": ["notepad.exe"],
    "calculadora": ["calculatorapp.exe", "calc.exe"],
    "calculadora do windows": ["calculatorapp.exe", "calc.exe"],
    "calc": ["calculatorapp.exe", "calc.exe"],
    "navegador": ["chrome.exe"],
    "browser": ["chrome.exe"],
    "chrome": ["chrome.exe"],
    "google chrome": ["chrome.exe"],
    "edge": ["msedge.exe"],
    "microsoft edge": ["msedge.exe"],
    "paint": ["mspaint.exe"],
    "whatsapp": ["whatsapp.exe"],
    "whatsapp desktop": ["whatsapp.exe"],
}

_ARTICLES = ("o ", "a ", "os ", "as ")
_FORBIDDEN = re.compile(r"[/\\:]")


def normalize_app_name(name: str) -> str:
    """Normaliza o nome falado: caixa, espaços, artigo inicial e pontuação final."""
    normalized = " ".join(str(name).casefold().split())
    normalized = normalized.rstrip(".,;!?\"' ").lstrip("\"' ")
    for article in _ARTICLES:
        if normalized.startswith(article):
            normalized = normalized[len(article):].lstrip()
            break
    return normalized


def resolve_app(name: str) -> AppCommand | None:
    """Resolve apenas aplicativos cadastrados; nunca caminhos ou programas do PATH."""
    if not isinstance(name, str) or _FORBIDDEN.search(name):
        return None
    return KNOWN_APPS.get(normalize_app_name(name))
