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
    "navegador": ["cmd.exe", "/c", "start", "", "chrome"],
    "browser": ["cmd.exe", "/c", "start", "", "chrome"],
    "chrome": ["cmd.exe", "/c", "start", "", "chrome"],
    "google chrome": ["cmd.exe", "/c", "start", "", "chrome"],
    "edge": ["cmd.exe", "/c", "start", "", "microsoft-edge:"] ,
    "microsoft edge": ["cmd.exe", "/c", "start", "", "microsoft-edge:"] ,
    "paint": ["mspaint.exe"],
    "spotify": ["cmd.exe", "/c", "start", "", "spotify:"],
    "vscode": ["cmd.exe", "/c", "start", "", "code"],
    "vs code": ["cmd.exe", "/c", "start", "", "code"],
    "visual studio code": ["cmd.exe", "/c", "start", "", "code"],
    "terminal": ["cmd.exe", "/c", "start", "", "wt"],
    "prompt de comando": ["cmd.exe", "/c", "start", "", "cmd"],
    "cmd": ["cmd.exe", "/c", "start", "", "cmd"],
    "powershell": ["cmd.exe", "/c", "start", "", "powershell"],
    "discord": ["cmd.exe", "/c", "start", "", "discord:"],
    "steam": ["cmd.exe", "/c", "start", "", "steam:"],
    "word": ["cmd.exe", "/c", "start", "", "winword"],
    "excel": ["cmd.exe", "/c", "start", "", "excel"],
    "powerpoint": ["cmd.exe", "/c", "start", "", "powerpnt"],
    "outlook": ["cmd.exe", "/c", "start", "", "outlook"],
    "firefox": ["cmd.exe", "/c", "start", "", "firefox"],
    "brave": ["cmd.exe", "/c", "start", "", "brave"],
    "obs": ["cmd.exe", "/c", "start", "", "obs64"],
    "configurações": ["cmd.exe", "/c", "start", "", "ms-settings:"],
    "configuracoes": ["cmd.exe", "/c", "start", "", "ms-settings:"],
    "gerenciador de tarefas": ["taskmgr.exe"],
    "painel de controle": ["control.exe"],
    "câmera": ["cmd.exe", "/c", "start", "", "microsoft.windows.camera:"],
    "camera": ["cmd.exe", "/c", "start", "", "microsoft.windows.camera:"],
    "relógio": ["cmd.exe", "/c", "start", "", "ms-clock:"],
    "youtube": ["cmd.exe", "/c", "start", "", "https://www.youtube.com"],
    "gmail": ["cmd.exe", "/c", "start", "", "https://mail.google.com"],
    "chatgpt": ["cmd.exe", "/c", "start", "", "https://chatgpt.com"],
    "github": ["cmd.exe", "/c", "start", "", "https://github.com"],
})

PROCESS_NAMES: dict[str, list[str]] = {
    "notepad": ["notepad.exe"],
    "bloco de notas": ["notepad.exe"],
    "calculadora": ["calculatorapp.exe", "calc.exe"],
    "calculadora do windows": ["calculatorapp.exe", "calc.exe"],
    "calc": ["calculatorapp.exe", "calc.exe"],
    "explorador": ["explorer.exe"],
    "explorer": ["explorer.exe"],
    "navegador": ["chrome.exe"],
    "browser": ["chrome.exe"],
    "chrome": ["chrome.exe"],
    "google chrome": ["chrome.exe"],
    "edge": ["msedge.exe"],
    "microsoft edge": ["msedge.exe"],
    "paint": ["mspaint.exe"],
    "whatsapp": ["whatsapp.exe"],
    "whatsapp desktop": ["whatsapp.exe"],
    "spotify": ["spotify.exe"],
    "vscode": ["code.exe"],
    "vs code": ["code.exe"],
    "visual studio code": ["code.exe"],
    "terminal": ["windowsterminal.exe"],
    "discord": ["discord.exe"],
    "steam": ["steam.exe"],
    "word": ["winword.exe"],
    "excel": ["excel.exe"],
    "powerpoint": ["powerpnt.exe"],
    "outlook": ["outlook.exe"],
    "firefox": ["firefox.exe"],
    "brave": ["brave.exe"],
    "obs": ["obs64.exe"],
    "gerenciador de tarefas": ["taskmgr.exe"],
}


def resolve_app(name: str) -> list[str] | None:
    normalized = name.casefold().strip()
    if normalized in KNOWN_APPS:
        return KNOWN_APPS[normalized]
    executable = shutil.which(name)
    return [executable] if executable else None


def find_app_in_text(text: str) -> str | None:
    """Encontra o aplicativo conhecido citado numa frase (o nome mais longo vence)."""
    import re

    value = " ".join(text.casefold().split())
    names = sorted(set(KNOWN_APPS) | set(PROCESS_NAMES), key=len, reverse=True)
    for name in names:
        if re.search(rf"(?<![\w]){re.escape(name)}(?![\w])", value):
            return name
    return None
