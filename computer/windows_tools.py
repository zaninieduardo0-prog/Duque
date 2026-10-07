"""Janelas e ajustes do Windows: listar, focar, minimizar, fechar, encaixar,
abrir páginas das Configurações, salvar captura de tela, brilho e Wi-Fi.

A lógica de escolha (qual janela, qual página) é pura e testável; as chamadas
ao Windows ficam atrás de ``IS_WINDOWS``. Fora do Windows as ferramentas dizem
honestamente que não conseguem.
"""

from __future__ import annotations

import os
import re
import subprocess
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

from . import windows_focus
from ._proc import CONSOLE_ENCODING, run_quiet
from .apps import installed_apps

IS_WINDOWS = windows_focus.IS_WINDOWS

# Apelido falado -> página "ms-settings:<página>".
SETTINGS_PAGES: dict[str, str] = {
    "inicio": "", "geral": "", "configuracoes": "",
    "wifi": "network-wifi", "wi fi": "network-wifi", "wireless": "network-wifi",
    "bluetooth": "bluetooth", "dispositivos": "bluetooth",
    "som": "sound", "audio": "sound", "volume": "sound", "microfone": "sound",
    "tela": "display", "display": "display", "monitor": "display", "resolucao": "display", "brilho": "display",
    "energia": "powersleep", "suspensao": "powersleep", "bateria": "batterysaver", "economia de bateria": "batterysaver",
    "atualizacoes": "windowsupdate", "atualizacao": "windowsupdate", "windows update": "windowsupdate", "update": "windowsupdate",
    "aplicativos": "appsfeatures", "apps": "appsfeatures", "programas": "appsfeatures",
    "notificacoes": "notifications", "notificacao": "notifications",
    "privacidade": "privacy", "rede": "network", "internet": "network", "redes": "network",
    "impressoras": "printers", "impressora": "printers",
    "mouse": "mousetouchpad", "touchpad": "devices-touchpad",
    "teclado": "typing", "digitacao": "typing",
    "data e hora": "dateandtime", "data": "dateandtime", "hora": "dateandtime", "relogio": "dateandtime",
    "idioma": "regionlanguage", "regiao": "regionlanguage",
    "personalizacao": "personalization", "papel de parede": "personalization-background",
    "plano de fundo": "personalization-background", "fundo de tela": "personalization-background",
    "modo escuro": "colors", "tema escuro": "colors", "cores": "colors", "temas": "themes",
    "armazenamento": "storagesense", "disco": "storagesense",
    "padrao": "defaultapps", "apps padrao": "defaultapps", "aplicativos padrao": "defaultapps",
    "navegador padrao": "defaultapps", "programas padrao": "defaultapps",
    "contas": "yourinfo", "conta": "yourinfo", "login": "signinoptions", "senha": "signinoptions",
    "vpn": "network-vpn", "proxy": "network-proxy", "modo aviao": "network-airplanemode",
    "sobre": "about", "sistema": "about", "foco": "quiethours", "nao perturbe": "quiethours",
    "acessibilidade": "easeofaccess", "lupa": "easeofaccess-magnifier",
    "inicializacao": "startupapps", "apps de inicializacao": "startupapps",
    "luz noturna": "nightlight", "multitarefa": "multitasking", "area de transferencia": "clipboard",
    "seguranca": "windowsdefender", "antivirus": "windowsdefender", "backup": "backup",
}
# O que a ferramenta diz quando não conhece a página pedida.
SETTINGS_OPTIONS = (
    "wifi", "bluetooth", "som", "tela", "energia", "bateria", "atualizações", "aplicativos",
    "notificações", "privacidade", "rede", "impressoras", "mouse", "teclado", "data e hora",
    "personalização", "papel de parede", "modo escuro", "armazenamento", "apps padrão",
)
_SETTINGS_IDS = frozenset(value for value in SETTINGS_PAGES.values() if value)
# Partes de título que nunca são fechadas: a interface do próprio TELEX.
PROTECTED_TITLE_PARTS = ("telex", "127.0.0.1:5000", "localhost:5000")
SNAP_SIDES = {"esquerda": 0x25, "left": 0x25, "direita": 0x27, "right": 0x27, "cima": 0x26, "maximizar": 0x26, "baixo": 0x28}
_FILLER = frozenset({"a", "o", "janela", "do", "da", "de", "app", "aplicativo", "programa"})


def plain(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", (text or "").casefold())
    no_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9.:]+", " ", no_accents).split())


def resolve_settings_page(page: str) -> str | None:
    """"wifi" -> "network-wifi"; "" -> "" (página inicial); desconhecido -> None."""
    key = plain(page).replace(".", " ").strip()
    key = re.sub(r"^(ms settings:|ms-settings:)", "", key).strip()
    key = re.sub(r"^(configuracoes|configuracao|ajustes) (de |do |da )?", "", key).strip() or key
    if key in ("", "configuracoes"):
        return ""
    if key in SETTINGS_PAGES:
        return SETTINGS_PAGES[key]
    if key.replace(" ", "-") in _SETTINGS_IDS:
        return key.replace(" ", "-")
    compact = key.replace(" ", "")
    for alias, target in SETTINGS_PAGES.items():
        if alias.replace(" ", "") == compact:
            return target
    return None


def is_protected_window(title: str) -> bool:
    value = (title or "").casefold()
    return any(part in value for part in PROTECTED_TITLE_PARTS)


def window_match_score(query: str, window: dict[str, Any]) -> int:
    """Quanto uma janela ({"title", "exe"}) combina com o pedido (0 = nada)."""
    wanted = plain(query)
    tokens = [token for token in wanted.split() if token not in _FILLER] or wanted.split()
    if not tokens:
        return 0
    title = plain(str(window.get("title") or ""))
    exe = plain(str(window.get("exe") or "")).removesuffix(".exe")
    phrase = " ".join(tokens)
    if title == phrase:
        return 100
    if exe and (exe == phrase or exe == phrase.replace(" ", "")):
        return 90
    if re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", title):
        return 80
    if phrase in title:
        return 70
    words = title.split()
    if all(any(word.startswith(token) for word in words) for token in tokens):
        return 60
    if exe and all(token in exe for token in tokens):
        return 50
    return 0


def match_window(query: str, windows: list[dict[str, Any]], *, allow_protected: bool = False) -> dict[str, Any] | None:
    """A janela que melhor combina (empate: a primeira, que é a mais recente na ordem Z)."""
    best: tuple[int, dict[str, Any]] | None = None
    for window in windows:
        if not allow_protected and is_protected_window(str(window.get("title") or "")):
            continue
        score = window_match_score(query, window)
        if score and (best is None or score > best[0]):
            best = (score, window)
    return best[1] if best else None


def parse_wlan_interfaces(text: str) -> dict[str, Any]:
    """Lê a saída de ``netsh wlan show interfaces`` (português ou inglês)."""
    info: dict[str, Any] = {}
    for line in (text or "").splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = plain(key), value.strip()
        if not value:
            continue
        if key in ("ssid",) and "ssid" not in info:
            info["ssid"] = value
        elif key in ("estado", "state") and "state" not in info:
            info["state"] = value
        elif key in ("sinal", "signal") and "signal" not in info:
            digits = re.search(r"\d+", value)
            info["signal"] = int(digits.group()) if digits else value
        elif key in ("nome", "name") and "interface" not in info:
            info["interface"] = value
        elif key in ("perfil", "profile") and "profile" not in info:
            info["profile"] = value
        elif key in ("tipo de radio", "radio type") and "radio" not in info:
            info["radio"] = value
        elif key in ("taxa de recepcao (mbps)", "receive rate (mbps)") and "receive_mbps" not in info:
            info["receive_mbps"] = value
    state = plain(str(info.get("state") or ""))
    info["connected"] = state in ("conectado", "connected")
    return info


def _error(message: str, **extra: Any) -> dict[str, Any]:
    return {"success": False, "error": message, "message": message, **extra}


def _startfile(target: str) -> None:
    opener = getattr(os, "startfile", None)
    if opener is None:
        raise RuntimeError("Isso só funciona no Windows.")
    opener(target)


def _pictures_dir() -> Path:
    from .file_tools import known_folder

    return known_folder("imagens") or Path.home() / "Pictures"


class WindowTools:
    """Controle de janelas e do Windows para o agente (contrato de AssistantTools)."""

    def _windows(self) -> list[dict[str, Any]]:
        """Janelas visíveis de nível superior (sem as de ferramenta e o "Program Manager")."""
        if not IS_WINDOWS:
            return []
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        found: list[dict[str, Any]] = []
        for hwnd, title in windows_focus._windows():
            if not title.strip() or title == "Program Manager":
                continue
            ex_style = int(user32.GetWindowLongW(hwnd, -20))  # GWL_EXSTYLE
            if ex_style & 0x00000080:  # WS_EX_TOOLWINDOW
                continue
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            try:
                exe = windows_focus._process_image(int(pid.value))
            except Exception:
                exe = ""
            found.append({"hwnd": int(hwnd), "title": title, "exe": exe, "minimized": bool(user32.IsIconic(hwnd))})
        return found

    def _find(self, title: str, *, closing: bool = False) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """(janela escolhida, erro). Nunca escolhe a interface do TELEX para fechar."""
        if not IS_WINDOWS:
            return None, _error("Controlar janelas só funciona no Windows.")
        if not str(title or "").strip():
            return None, _error("Diga qual janela (parte do título ou o nome do programa).")
        windows = self._windows()
        allow = (not closing) and is_protected_window(title)
        window = match_window(title, windows, allow_protected=allow)
        if window is None:
            if closing and match_window(title, windows, allow_protected=True):
                return None, _error("Essa é a janela do próprio TELEX; não vou fechá-la.")
            return None, _error(f"Não achei nenhuma janela com '{title}'.", open_windows=[w["title"] for w in windows[:15]])
        return window, None

    def windows_list(self) -> dict[str, Any]:
        if not IS_WINDOWS:
            return _error("Listar janelas só funciona no Windows.", windows=[])
        windows = self._windows()
        if not windows:
            return {"message": "Não há janelas abertas.", "windows": []}
        names = "; ".join(w["title"] for w in windows[:10])
        return {"message": f"{len(windows)} janela(s) aberta(s): {names}.", "windows": windows}

    def window_focus(self, title: str) -> dict[str, Any]:
        window, error = self._find(title)
        if error or window is None:
            return error or _error("Janela não encontrada.")
        ok = windows_focus._focus_hwnd(window["hwnd"])
        if not ok:
            return _error(f"Achei '{window['title']}', mas o Windows não deixou trazer para a frente.", window=window)
        return {"message": f"Trouxe para a frente: {window['title']}.", "window": window}

    def _show(self, title: str, command: int, verb: str) -> dict[str, Any]:
        window, error = self._find(title)
        if error or window is None:
            return error or _error("Janela não encontrada.")
        import ctypes

        ctypes.windll.user32.ShowWindow(window["hwnd"], command)  # type: ignore[attr-defined]
        return {"message": f"{verb}: {window['title']}.", "window": window}

    def window_minimize(self, title: str) -> dict[str, Any]:
        return self._show(title, 6, "Minimizei")  # SW_MINIMIZE

    def window_maximize(self, title: str) -> dict[str, Any]:
        return self._show(title, 3, "Maximizei")  # SW_MAXIMIZE

    def window_restore(self, title: str) -> dict[str, Any]:
        return self._show(title, 9, "Restaurei")  # SW_RESTORE

    def window_close(self, title: str) -> dict[str, Any]:
        window, error = self._find(title, closing=True)
        if error or window is None:
            return error or _error("Janela não encontrada.")
        if is_protected_window(window["title"]):  # defesa extra
            return _error("Essa é a janela do próprio TELEX; não vou fechá-la.")
        import ctypes

        ctypes.windll.user32.PostMessageW(window["hwnd"], 0x0010, 0, 0)  # type: ignore[attr-defined]  # WM_CLOSE
        return {
            "message": f"Pedi para fechar: {window['title']}. Se houver algo não salvo, o programa vai perguntar.",
            "window": window,
        }

    def show_desktop(self) -> dict[str, Any]:
        if not IS_WINDOWS:
            return _error("Mostrar a área de trabalho só funciona no Windows.")
        windows_focus._keys(0x5B, 0x44)  # Win+D
        return {"message": "Mostrei a área de trabalho (de novo devolve as janelas)."}

    def snap_window(self, title: str, side: str = "esquerda") -> dict[str, Any]:
        key = SNAP_SIDES.get(plain(side))
        if key is None:
            return _error("Lado inválido: use esquerda ou direita.")
        window, error = self._find(title)
        if error or window is None:
            return error or _error("Janela não encontrada.")
        if not windows_focus._focus_hwnd(window["hwnd"]):
            return _error(f"Não consegui focar '{window['title']}' para encaixar.", window=window)
        windows_focus._keys(0x5B, key)  # Win+seta
        return {"message": f"Encaixei {window['title']} à {plain(side)}.", "window": window}

    def open_settings(self, page: str = "") -> dict[str, Any]:
        target = resolve_settings_page(page)
        if target is None:
            options = ", ".join(SETTINGS_OPTIONS)
            return _error(f"Não conheço a página '{page}' das Configurações. Opções: {options}.")
        uri = f"ms-settings:{target}"
        try:
            _startfile(uri)
        except (OSError, RuntimeError) as exc:
            return _error(f"Não consegui abrir as Configurações: {exc}", uri=uri)
        label = page.strip() or "início"
        return {"message": f"Abri as Configurações em {label}.", "uri": uri}

    def screenshot_save(self, name: str = "") -> dict[str, Any]:
        try:
            from PIL import ImageGrab  # type: ignore[import-not-found]
        except ImportError:
            return _error("Para salvar a tela preciso do Pillow (pip install pillow).")
        folder = _pictures_dir() / "Screenshots"
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = ""
        if name and name.strip():
            from .file_tools import sanitize_filename

            try:
                suffix = "_" + sanitize_filename(name).removesuffix(".png")
            except ValueError:
                suffix = ""
        target = folder / f"TELEX_{stamp}{suffix}.png"
        try:
            image = ImageGrab.grab(all_screens=True)
            folder.mkdir(parents=True, exist_ok=True)
            image.save(target, "PNG")
        except Exception as exc:
            return _error(f"Não consegui capturar a tela: {type(exc).__name__}: {exc}")
        return {"message": f"Salvei a captura em {target.name}, na pasta Screenshots.", "path": str(target)}

    def brightness_set(self, percent: int | float) -> dict[str, Any]:
        if not IS_WINDOWS:
            return _error("Ajustar o brilho só funciona no Windows.")
        try:
            value = max(0, min(100, int(round(float(percent)))))
        except (TypeError, ValueError):
            return _error("Diga o brilho em porcentagem (0 a 100).")
        script = (
            "$m = Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods -ErrorAction Stop; "
            f"$m.WmiSetBrightness(1, {value}) | Out-Null"
        )
        try:
            done = run_quiet(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout=20)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return _error(f"Não consegui ajustar o brilho: {type(exc).__name__}.")
        if done.returncode != 0:
            return _error(
                "Esta tela não aceita ajuste de brilho pelo Windows (comum em monitores de desktop). "
                "Use os botões do monitor.",
                detail=(done.stderr or "").strip()[:300],
            )
        return {"message": f"Brilho em {value}%.", "percent": value}

    def wifi_status(self) -> dict[str, Any]:
        if not IS_WINDOWS:
            return _error("Ver o Wi-Fi só funciona no Windows.")
        try:
            done = run_quiet(["netsh", "wlan", "show", "interfaces"], timeout=10, encoding=CONSOLE_ENCODING)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return _error(f"Não consegui consultar o Wi-Fi: {type(exc).__name__}.")
        info = parse_wlan_interfaces(done.stdout)
        if not info.get("state") and not info.get("ssid"):
            return {"message": "Não encontrei adaptador Wi-Fi (talvez esteja no cabo).", **info}
        if info["connected"]:
            signal = info.get("signal")
            tail = f", sinal {signal}%" if isinstance(signal, int) else ""
            return {"message": f"Conectado ao Wi-Fi {info.get('ssid', '?')}{tail}.", **info}
        return {"message": f"Wi-Fi desconectado ({info.get('state', 'sem estado')}).", **info}

    def apps_list(self, query: str = "") -> dict[str, Any]:
        names = installed_apps(query)
        if not names:
            text = f"Não achei apps instalados com '{query}'." if query else "Não encontrei apps no Menu Iniciar."
            return {"message": text, "apps": []}
        shown = ", ".join(names[:25])
        more = f" (e mais {len(names) - 25})" if len(names) > 25 else ""
        return {"message": f"Apps instalados: {shown}{more}.", "apps": names}

    # registro --------------------------------------------------------------------
    SPECS: list[tuple[str, str, tuple[str, ...], dict[str, Any]]] = [
        ("windows_list", "Lista as janelas abertas (título, programa, minimizada)", (), {}),
        ("window_focus", "Traz para a frente a janela pelo título ou nome do programa (ex.: 'excel', 'YouTube')", ("title",), {"title": str}),
        ("window_minimize", "Minimiza a janela indicada (título ou programa)", ("title",), {"title": str}),
        ("window_maximize", "Maximiza a janela indicada (título ou programa)", ("title",), {"title": str}),
        ("window_restore", "Restaura a janela indicada ao tamanho normal", ("title",), {"title": str}),
        ("window_close", "Fecha a janela indicada (só ela; nunca a do TELEX)", ("title",), {"title": str}),
        ("show_desktop", "Mostra a área de trabalho (minimiza tudo, como Win+D)", (), {}),
        ("snap_window", "Encaixa a janela numa metade da tela: esquerda ou direita", ("title", "side"), {"title": str, "side": str}),
        ("open_settings", "Abre uma página das Configurações do Windows (wifi, bluetooth, som, tela, energia, atualizações, aplicativos, privacidade, mouse, teclado, data e hora, papel de parede, modo escuro, armazenamento, apps padrão...)", (), {"page": str}),
        ("screenshot_save", "Salva uma captura da tela inteira em Imagens\\Screenshots e devolve o caminho", (), {"name": str}),
        ("brightness_set", "Ajusta o brilho da tela (0 a 100; só telas de notebook/compatíveis)", ("percent",), {"percent": (int, float)}),
        ("wifi_status", "Mostra o Wi-Fi atual: rede (SSID), sinal e estado", (), {}),
        ("apps_list", "Lista os apps instalados (Menu Iniciar), filtrando por um nome opcional", (), {"query": str}),
    ]
    RISK: dict[str, str] = {
        "windows_list": "low", "window_focus": "low", "window_minimize": "low", "window_maximize": "low",
        "window_restore": "low", "window_close": "medium", "show_desktop": "low", "snap_window": "low",
        "open_settings": "low", "screenshot_save": "low", "brightness_set": "low", "wifi_status": "low",
        "apps_list": "low",
    }

    def register(self, executor: Any, schemas: Any | None = None) -> None:
        from brain.tool_schema import ToolSpec

        for name, description, required, types in self.SPECS:
            executor.register(name, getattr(self, name))
            if schemas is not None:
                schemas.register(ToolSpec(name, description, required, types))
