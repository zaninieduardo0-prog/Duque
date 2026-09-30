import os
import subprocess
import webbrowser
from pathlib import Path


# ============================================================
# CAMINHOS DE PROGRAMAS
# ============================================================

PROGRAMAS = {
    "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "google chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",

    "calculadora": "calc",
    "calc": "calc",

    "bloco de notas": "notepad",
    "notepad": "notepad",

    "explorador": "explorer",
    "explorador de arquivos": "explorer",

    "cmd": "cmd",
    "prompt de comando": "cmd",
}


# ============================================================
# ABRIR SITE
# ============================================================

def abrir_site(url: str) -> str:
    """Abre um site no navegador padrão."""

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        webbrowser.open(url)
        return f"Abri o site {url}."

    except Exception as erro:
        return f"Não consegui abrir o site: {erro}"


# ============================================================
# ABRIR PROGRAMA
# ============================================================

def abrir_programa(programa: str) -> str:
    """Abre um programa instalado no Windows."""

    nome = programa.lower().strip()

    caminho = PROGRAMAS.get(nome)

    if not caminho:
        return (
            f"Não tenho o programa '{programa}' "
            "cadastrado para abertura automática."
        )

    # --------------------------------------------------------
    # Verifica caminhos absolutos
    # --------------------------------------------------------

    if os.path.isabs(caminho):

        if not os.path.isfile(caminho):
            return (
                f"O programa '{programa}' está configurado, "
                f"mas o arquivo não foi encontrado em:\n{caminho}"
            )

    # --------------------------------------------------------
    # Tenta abrir
    # --------------------------------------------------------

    try:

        if os.path.isabs(caminho):
            subprocess.Popen([caminho])

        else:
            subprocess.Popen(caminho)

        return f"Abri o {programa}."

    except Exception as erro:
        return (
            f"Não consegui abrir {programa}: {erro}"
        )


# ============================================================
# ABRIR PASTA
# ============================================================

def abrir_pasta(caminho: str) -> str:
    """Abre uma pasta no Explorador de Arquivos."""

    caminho = os.path.expandvars(caminho)
    caminho = os.path.expanduser(caminho)

    if not os.path.exists(caminho):
        return f"A pasta não existe: {caminho}"

    try:
        os.startfile(caminho)
        return f"Abri a pasta {caminho}."

    except Exception as erro:
        return f"Não consegui abrir a pasta: {erro}"


# ============================================================
# ABRIR ARQUIVO
# ============================================================

def abrir_arquivo(caminho: str) -> str:
    """Abre um arquivo usando o programa padrão do Windows."""

    caminho = os.path.expandvars(caminho)
    caminho = os.path.expanduser(caminho)

    if not os.path.isfile(caminho):
        return f"O arquivo não existe: {caminho}"

    try:
        os.startfile(caminho)
        return f"Abri o arquivo {caminho}."

    except Exception as erro:
        return f"Não consegui abrir o arquivo: {erro}"