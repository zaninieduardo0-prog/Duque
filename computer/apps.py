from __future__ import annotations

import os
import re
import threading
import time
import unicodedata
from pathlib import Path

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
    "instagram": ["cmd.exe", "/c", "start", "", "https://www.instagram.com"],
    "chatgpt": ["cmd.exe", "/c", "start", "", "https://chatgpt.com"],
    "github": ["cmd.exe", "/c", "start", "", "https://github.com"],
})

PROCESS_NAMES: dict[str, list[str]] = {
    "notepad": ["notepad.exe"],
    "bloco de notas": ["notepad.exe"],
    "calculadora": ["calculatorapp.exe", "calculator.exe", "calc.exe"],
    "calculadora do windows": ["calculatorapp.exe", "calculator.exe", "calc.exe"],
    "calc": ["calculatorapp.exe", "calculator.exe", "calc.exe"],
    # explorer.exe NÃO entra aqui: é o shell do Windows (barra de tarefas e área
    # de trabalho). Está sempre "rodando" e fechá-lo derrubaria a interface.
    "navegador": ["chrome.exe"],
    "browser": ["chrome.exe"],
    "chrome": ["chrome.exe"],
    "google chrome": ["chrome.exe"],
    "edge": ["msedge.exe"],
    "microsoft edge": ["msedge.exe"],
    "paint": ["mspaint.exe"],
    # O WhatsApp novo (loja da Microsoft) roda como WhatsApp.Root.exe.
    "whatsapp": ["whatsapp.exe", "whatsapp.root.exe"],
    "whatsapp desktop": ["whatsapp.exe", "whatsapp.root.exe"],
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


_PATH_LIKE = re.compile(r"[/\\:]")


def resolve_app(name: str) -> list[str] | None:
    """Só aplicativos cadastrados. Nunca caminhos nem programas soltos do PATH.

    O antigo recurso ao ``shutil.which`` deixava o modelo rodar qualquer
    executável (``format``, ``python``...) como "abrir app", de risco baixo.
    """
    if not isinstance(name, str) or _PATH_LIKE.search(name):
        return None
    normalized = " ".join(name.casefold().split()).strip(" .,;!?\"'")
    known = KNOWN_APPS.get(normalized)
    if known is not None:
        return known
    # Um app cadastrado citado na frase ("minha calculadora") vence o Menu Iniciar:
    # quem chama resolve isso com find_app_in_text.
    if not normalized or find_app_in_text(normalized):
        return None
    # Último recurso: um atalho do Menu Iniciar (só caminhos achados no índice,
    # nunca um caminho vindo do pedido). controller.launch abre via os.startfile.
    try:
        shortcut = find_installed_app(normalized)
    except Exception:
        shortcut = None
    if shortcut:
        return ["cmd.exe", "/c", "start", "", shortcut]
    return None


def find_app_in_text(text: str) -> str | None:
    """Encontra o aplicativo conhecido citado numa frase (o nome mais longo vence)."""
    import re

    value = " ".join(text.casefold().split())
    names = sorted(set(KNOWN_APPS) | set(PROCESS_NAMES), key=len, reverse=True)
    for name in names:
        if re.search(rf"(?<![\w]){re.escape(name)}(?![\w])", value):
            return name
    return None


# Versão web usada quando o app não está instalado (ou não respondeu).
WEB_FALLBACK: dict[str, str] = {
    "whatsapp": "https://web.whatsapp.com/",
    "whatsapp desktop": "https://web.whatsapp.com/",
    "spotify": "https://open.spotify.com/",
    "discord": "https://discord.com/app",
    "youtube": "https://www.youtube.com/",
    "gmail": "https://mail.google.com/",
}

# Protocolo do Windows que precisa estar registrado para o comando funcionar.
PROTOCOLS: dict[str, str] = {
    "whatsapp": "whatsapp",
    "whatsapp desktop": "whatsapp",
    "spotify": "spotify",
    "discord": "discord",
}

CHROME_NAMES = frozenset({"chrome", "google chrome", "navegador", "browser"})


def protocol_registered(protocol: str) -> bool:
    """O Windows sabe abrir "<protocolo>:"? (sem isso aparece a janela "Procurar app")."""
    try:
        import winreg  # type: ignore[import-not-found]
    except ImportError:
        return True
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, protocol):  # type: ignore[attr-defined]
            return True
    except OSError:
        return False


# --- aplicativos instalados (atalhos do Menu Iniciar) -------------------------------

SHORTCUT_EXTENSIONS = (".lnk", ".url", ".appref-ms")
START_MENU_TTL = 600.0  # o índice vale 10 minutos
# Atalhos que não são o app em si.
_IGNORED_SHORTCUT_WORDS = (
    "uninstall", "desinstalar", "desinstalacao", "readme", "leia-me", "leiame",
    "help", "ajuda", "license", "licenca", "release notes", "documentation", "documentacao",
)
# Interpretadores e consoles: abrir pelo Menu Iniciar seria executar comandos soltos
# (o mesmo motivo de resolve_app não aceitar "python3"). Os consoles úteis
# (cmd, PowerShell, terminal) estão em KNOWN_APPS, explícitos.
_BLOCKED_SHORTCUT_TOKENS = frozenset({
    "python", "python3", "pythonw", "py", "idle", "cmd", "powershell", "pwsh", "bash", "wsl",
    "node", "nodejs", "regedit", "prompt", "command", "console", "shell",
})
# Palavras que não ajudam a distinguir um app ("o aplicativo do Word").
_FILLER_TOKENS = frozenset({
    "o", "a", "os", "as", "do", "da", "de", "dos", "das", "meu", "minha", "app", "aplicativo",
    "programa", "microsoft", "the",
})
# Apelidos falados -> nome do atalho.
APP_ALIASES: dict[str, str] = {
    "vscode": "visual studio code", "vs code": "visual studio code", "code": "visual studio code",
    "ppt": "powerpoint", "power point": "powerpoint", "one note": "onenote",
    "teams": "teams", "acrobat": "adobe acrobat", "reader": "adobe acrobat reader",
}

_index_lock = threading.Lock()
_index_cache: dict[tuple[str, ...], tuple[float, dict[str, str]]] = {}


def _plain_tokens(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", (text or "").casefold())
    plain = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.findall(r"[a-z0-9]+", plain)


def start_menu_dirs() -> list[Path]:
    """Pastas do Menu Iniciar (de todos os usuários e do usuário atual)."""
    dirs: list[Path] = []
    for variable in ("ProgramData", "APPDATA"):
        base = os.environ.get(variable)
        if base:
            folder = Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            if folder.is_dir():
                dirs.append(folder)
    return dirs


def _ignored_shortcut(stem: str) -> bool:
    plain = " ".join(_plain_tokens(stem))
    if any(word in plain for word in _IGNORED_SHORTCUT_WORDS):
        return True
    return bool(_BLOCKED_SHORTCUT_TOKENS.intersection(_plain_tokens(stem)))


def build_app_index(roots: list[Path] | tuple[Path, ...]) -> dict[str, str]:
    """{nome do atalho: caminho} de todos os atalhos (recursivo) nas pastas dadas."""
    index: dict[str, str] = {}
    for root in roots:
        try:
            walker = os.walk(root)
        except OSError:
            continue
        for current, dirs, files in walker:
            dirs.sort()
            for file in sorted(files):
                path = Path(current) / file
                if path.suffix.casefold() not in SHORTCUT_EXTENSIONS:
                    continue
                stem = path.name[: -len(path.suffix)]
                if not stem or _ignored_shortcut(stem):
                    continue
                index.setdefault(stem, str(path))  # o primeiro (ProgramData) vence
    return index


def app_index(roots: list[Path] | tuple[Path, ...] | None = None, *, refresh: bool = False) -> dict[str, str]:
    """Índice do Menu Iniciar com cache de ``START_MENU_TTL`` segundos."""
    folders = tuple(roots) if roots is not None else tuple(start_menu_dirs())
    key = tuple(str(folder) for folder in folders)
    now = time.monotonic()
    with _index_lock:
        cached = _index_cache.get(key)
        if cached and not refresh and now - cached[0] < START_MENU_TTL:
            return cached[1]
    index = build_app_index(folders)
    with _index_lock:
        _index_cache[key] = (now, index)
    return index


def _meaningful(tokens: list[str]) -> list[str]:
    kept = [token for token in tokens if token not in _FILLER_TOKENS]
    return kept or tokens


def app_match_score(query: str, name: str) -> int:
    """Quanto o nome de um atalho combina com o pedido (0 = não combina)."""
    raw = _plain_tokens(query)
    alias = APP_ALIASES.get(" ".join(raw)) or APP_ALIASES.get("".join(raw))
    wanted = _meaningful(_plain_tokens(alias) if alias else raw)
    have = _meaningful(_plain_tokens(name))
    if not wanted or not have:
        return 0
    extra = max(0, len(have) - len(wanted))
    if wanted == have:
        return 100
    if "".join(wanted) == "".join(have):
        return 95
    if all(token in have for token in wanted):
        return max(60, 80 - 5 * extra)
    if all(len(token) >= 4 and any(item.startswith(token) for item in have) for token in wanted):
        return max(30, 50 - 5 * extra)
    return 0


def match_app_name(query: str, names: list[str] | tuple[str, ...] | set[str] | dict[str, str]) -> str | None:
    """O nome de atalho que melhor combina (empate: o mais curto)."""
    if not isinstance(query, str) or _BLOCKED_SHORTCUT_TOKENS.intersection(_plain_tokens(query)):
        return None
    best: tuple[int, int, str] | None = None
    for name in names:
        score = app_match_score(query, name)
        if score and (best is None or (score, -len(name)) > (best[0], best[1])):
            best = (score, -len(name), name)
    return best[2] if best else None


def find_installed_app(name: str, roots: list[Path] | tuple[Path, ...] | None = None) -> str | None:
    """Caminho do atalho do Menu Iniciar que abre o app pedido (ex.: "excel" -> Excel.lnk).

    Só devolve caminhos achados no índice: um caminho vindo do pedido é recusado.
    """
    if not isinstance(name, str) or not name.strip() or _PATH_LIKE.search(name):
        return None
    index = app_index(roots)
    found = match_app_name(name, index)
    return index[found] if found else None


def installed_apps(query: str = "", roots: list[Path] | tuple[Path, ...] | None = None, limit: int = 200) -> list[str]:
    """Nomes dos apps do Menu Iniciar (filtrados por ``query`` quando dada), em ordem."""
    names = sorted(app_index(roots), key=str.casefold)
    if query and query.strip():
        wanted = " ".join(_plain_tokens(query))
        names = [n for n in names if app_match_score(query, n) or wanted in " ".join(_plain_tokens(n))]
    return names[: max(1, int(limit))]
