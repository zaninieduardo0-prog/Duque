"""Ferramentas do dia a dia: hora, clima, contas, notas, timers, mídia,
volume, área de transferência, estado do sistema, pastas, arquivos e atalhos.

Toda ferramenta devolve um dicionário com "message" (frase pronta para ser
dita) e os dados estruturados, para o agente verificar o resultado real.
"""

from __future__ import annotations

import ast
import json
import math
import operator
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from memory.memory import Memory, MemoryLayer

IS_WINDOWS = sys.platform.startswith("win")

WEEKDAYS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]

WEATHER_CODES = {
    0: "céu limpo", 1: "predominantemente limpo", 2: "parcialmente nublado", 3: "nublado",
    45: "neblina", 48: "neblina", 51: "garoa fraca", 53: "garoa", 55: "garoa forte",
    61: "chuva fraca", 63: "chuva", 65: "chuva forte", 66: "chuva congelante", 67: "chuva congelante",
    71: "neve fraca", 73: "neve", 75: "neve forte", 80: "pancadas de chuva", 81: "pancadas de chuva",
    82: "pancadas fortes", 95: "trovoadas", 96: "trovoadas com granizo", 99: "trovoadas com granizo",
}

MEDIA_KEYS = {
    "play_pause": 0xB3, "tocar": 0xB3, "pausar": 0xB3, "play": 0xB3, "pause": 0xB3,
    "next": 0xB0, "proxima": 0xB0, "próxima": 0xB0,
    "previous": 0xB1, "anterior": 0xB1,
    "stop": 0xB2, "parar": 0xB2,
    "mute": 0xAD, "mudo": 0xAD,
}
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF

KNOWN_FOLDERS = {
    "downloads": "Downloads", "download": "Downloads",
    "documentos": "Documents", "documents": "Documents",
    "area de trabalho": "Desktop", "área de trabalho": "Desktop", "desktop": "Desktop",
    "imagens": "Pictures", "fotos": "Pictures", "pictures": "Pictures",
    "musicas": "Music", "músicas": "Music", "music": "Music",
    "videos": "Videos", "vídeos": "Videos",
    "pasta pessoal": "", "home": "",
}

_BINARY = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "sqrt": math.sqrt, "raiz": math.sqrt, "abs": abs, "round": round, "arredondar": round,
    "sin": math.sin, "cos": math.cos, "tan": math.tan, "log": math.log, "log10": math.log10,
    "exp": math.exp, "floor": math.floor, "ceil": math.ceil,
}
_CONSTANTS = {"pi": math.pi, "e": math.e}


def safe_eval(expression: str) -> float:
    """Avalia uma expressão matemática sem executar código arbitrário."""
    text = expression.strip().replace("×", "*").replace("÷", "/").replace("^", "**")
    text = text.replace(" x ", " * ")
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    tree = ast.parse(text, mode="eval")

    def visit(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 1000:
                raise ValueError("expoente grande demais")
            return _BINARY[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](visit(node.operand))
        if isinstance(node, ast.Name) and node.id in _CONSTANTS:
            return _CONSTANTS[node.id]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCTIONS and not node.keywords:
            return _FUNCTIONS[node.func.id](*(visit(arg) for arg in node.args))
        raise ValueError("expressão não suportada")

    return visit(tree)


def format_number(value: float) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int):
        return f"{value:,}".replace(",", ".")
    return f"{value:,.6f}".rstrip("0").rstrip(",").replace(",", "X").replace(".", ",").replace("X", ".")


def describe_now(moment: datetime) -> str:
    return (
        f"São {moment:%H:%M} de {WEEKDAYS[moment.weekday()]}, "
        f"{moment.day} de {MONTHS[moment.month - 1]} de {moment.year}."
    )


def describe_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    parts = []
    if hours:
        parts.append(f"{hours} hora{'s' if hours > 1 else ''}")
    if minutes:
        parts.append(f"{minutes} minuto{'s' if minutes > 1 else ''}")
    if secs or not parts:
        parts.append(f"{secs} segundo{'s' if secs != 1 else ''}")
    return " e ".join(parts)


def _http_json(url: str, timeout: float = 8) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "duque"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def web_alternative(target: str) -> str | None:
    """whatsapp://send?... -> https://web.whatsapp.com/send?... (app não instalado)."""
    if target.startswith("whatsapp://"):
        rest = target[len("whatsapp://"):]
        return "https://web.whatsapp.com/" + rest
    return None


def _open_target(target: str) -> None:
    if IS_WINDOWS:
        from .apps import protocol_registered
        from .chrome import open_in_chrome

        web = web_alternative(target)
        if web and not protocol_registered(target.split(":", 1)[0]):
            target = web
        if target.startswith(("http://", "https://")) and os.getenv("DUQUE_BROWSER", "chrome").casefold() == "chrome":
            try:
                if open_in_chrome(target):
                    return
            except Exception:
                pass
        os.startfile(target)  # type: ignore[attr-defined]  # noqa: S606
    else:
        subprocess.Popen(["xdg-open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _press_key(vk: int, times: int = 1) -> None:
    if not IS_WINDOWS:
        raise RuntimeError("controle de mídia e volume disponível apenas no Windows")
    import ctypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    for _ in range(max(1, times)):
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, 0x0002, 0)
        time.sleep(0.02)


@dataclass(slots=True)
class Timer:
    id: str
    label: str
    ends_at: float
    handle: threading.Timer


class AssistantTools:
    def __init__(
        self,
        memory: Memory | None = None,
        *,
        notify: Callable[[str], Any] | None = None,
        fetch_json: Callable[[str], Any] = _http_json,
        open_target: Callable[[str], None] = _open_target,
        press_key: Callable[[int, int], None] = _press_key,
        clock: Callable[[], datetime] = datetime.now,
        default_city: str | None = None,
    ) -> None:
        self.memory = memory
        self.notify = notify
        self.fetch_json = fetch_json
        self.open_target = open_target
        self.press_key = press_key
        self.clock = clock
        self.default_city = default_city or os.getenv("DUQUE_CITY", "Piracicaba")
        self._timers: dict[str, Timer] = {}
        self._lock = threading.Lock()

    # tempo -------------------------------------------------------------------
    def current_time(self) -> dict[str, Any]:
        moment = self.clock()
        return {"message": describe_now(moment), "iso": moment.isoformat(timespec="seconds")}

    # clima -------------------------------------------------------------------
    def weather(self, city: str = "") -> dict[str, Any]:
        name = (city or self.default_city).strip()
        query = urllib.parse.urlencode({"name": name, "count": 1, "language": "pt", "format": "json"})
        places = self.fetch_json(f"https://geocoding-api.open-meteo.com/v1/search?{query}")
        results = places.get("results") if isinstance(places, dict) else None
        if not results:
            return {"success": False, "error": f"Não encontrei a cidade '{name}'."}
        place = results[0]
        params = urllib.parse.urlencode({
            "latitude": place["latitude"], "longitude": place["longitude"],
            "current": "temperature_2m,apparent_temperature,weather_code,relative_humidity_2m,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": "auto", "forecast_days": 1,
        })
        data = self.fetch_json(f"https://api.open-meteo.com/v1/forecast?{params}")
        current, daily = data["current"], data["daily"]
        sky = WEATHER_CODES.get(int(current["weather_code"]), "tempo variável")
        rain = daily.get("precipitation_probability_max", [None])[0]
        message = (
            f"Em {place['name']}: {round(current['temperature_2m'])}°C, {sky}, sensação de "
            f"{round(current['apparent_temperature'])}°C. Hoje entre {round(daily['temperature_2m_min'][0])}° e "
            f"{round(daily['temperature_2m_max'][0])}°"
            + (f", {rain}% de chance de chuva." if rain is not None else ".")
        )
        return {"message": message, "city": place["name"], "current": current, "daily": daily}

    # contas ------------------------------------------------------------------
    def calculate(self, expression: str) -> dict[str, Any]:
        try:
            value = safe_eval(expression)
        except ZeroDivisionError:
            return {"success": False, "error": "Divisão por zero."}
        except (ValueError, SyntaxError, TypeError, OverflowError) as exc:
            return {"success": False, "error": f"Não consegui calcular '{expression}': {exc}"}
        return {"message": f"{expression.strip()} = {format_number(value)}", "value": value}

    # notas -------------------------------------------------------------------
    def _notes(self) -> list[dict[str, Any]]:
        if self.memory is None:
            return []
        notes = self.memory.recall(MemoryLayer.PERSONAL, "notas", [])
        return notes if isinstance(notes, list) else []

    def note_add(self, text: str) -> dict[str, Any]:
        if self.memory is None:
            return {"success": False, "error": "Memória indisponível"}
        if not text.strip():
            return {"success": False, "error": "A nota está vazia"}
        notes = self._notes()
        notes.append({"text": text.strip(), "at": self.clock().isoformat(timespec="minutes")})
        self.memory.remember(MemoryLayer.PERSONAL, "notas", notes)
        return {"message": f"Anotado. Você tem {len(notes)} nota(s).", "count": len(notes)}

    def notes_list(self) -> dict[str, Any]:
        notes = self._notes()
        if not notes:
            return {"message": "Você não tem notas.", "notes": []}
        lines = [f"{index}. {note['text']}" for index, note in enumerate(notes, 1)]
        return {"message": "Suas notas:\n" + "\n".join(lines), "notes": notes}

    def note_delete(self, index: int) -> dict[str, Any]:
        notes = self._notes()
        if not 1 <= index <= len(notes):
            return {"success": False, "error": f"Não existe a nota {index}."}
        removed = notes.pop(index - 1)
        if self.memory is not None:
            self.memory.remember(MemoryLayer.PERSONAL, "notas", notes)
        return {"message": f"Apaguei a nota: {removed['text']}", "removed": removed}

    # timers ------------------------------------------------------------------
    def timer_set(self, seconds: int | float, label: str = "") -> dict[str, Any]:
        seconds = float(seconds)
        if not 1 <= seconds <= 7 * 24 * 3600:
            return {"success": False, "error": "O timer precisa ter entre 1 segundo e 7 dias."}
        timer_id = uuid4().hex[:6]
        name = label.strip() or "timer"

        def fire() -> None:
            with self._lock:
                self._timers.pop(timer_id, None)
            if self.notify:
                self.notify(f"Du, o {name} de {describe_duration(seconds)} terminou." if name == "timer" else f"Du, lembrete: {name}.")

        handle = threading.Timer(seconds, fire)
        handle.daemon = True
        with self._lock:
            self._timers[timer_id] = Timer(timer_id, name, time.time() + seconds, handle)
        handle.start()
        return {"message": f"Timer de {describe_duration(seconds)} iniciado" + (f" para {name}." if name != "timer" else "."), "id": timer_id}

    def timers_list(self) -> dict[str, Any]:
        with self._lock:
            timers = list(self._timers.values())
        if not timers:
            return {"message": "Nenhum timer ativo.", "timers": []}
        items = [{"id": t.id, "label": t.label, "remaining": max(0, t.ends_at - time.time())} for t in timers]
        lines = [f"{item['label']}: faltam {describe_duration(item['remaining'])}" for item in items]
        return {"message": "\n".join(lines), "timers": items}

    def timer_cancel(self, id: str = "") -> dict[str, Any]:
        with self._lock:
            targets = [self._timers.pop(id)] if id in self._timers else ([] if id else list(self._timers.values()))
            if not id:
                self._timers.clear()
        for timer in targets:
            timer.handle.cancel()
        if not targets:
            return {"success": False, "error": "Nenhum timer correspondente."}
        return {"message": f"Cancelei {len(targets)} timer(s).", "cancelled": [t.id for t in targets]}

    # mídia e volume ------------------------------------------------------------
    def media(self, action: str) -> dict[str, Any]:
        key = MEDIA_KEYS.get(action.casefold().strip())
        if key is None:
            return {"success": False, "error": f"Ação de mídia desconhecida: {action}. Use play_pause, next, previous, stop ou mute."}
        self.press_key(key, 1)
        return {"message": "Feito.", "action": action}

    def volume(self, direction: str, steps: int = 5) -> dict[str, Any]:
        value = direction.casefold().strip()
        if value in {"up", "aumentar", "mais", "subir"}:
            self.press_key(VK_VOLUME_UP, max(1, min(int(steps), 50)))
            return {"message": "Aumentei o volume.", "direction": "up", "steps": steps}
        if value in {"down", "diminuir", "menos", "baixar"}:
            self.press_key(VK_VOLUME_DOWN, max(1, min(int(steps), 50)))
            return {"message": "Diminuí o volume.", "direction": "down", "steps": steps}
        if value in {"mute", "mudo", "silenciar", "desmutar", "unmute"}:
            self.press_key(MEDIA_KEYS["mute"], 1)
            return {"message": "Alternei o mudo.", "direction": "mute"}
        return {"success": False, "error": "Direção inválida: use up, down ou mute."}

    # área de transferência --------------------------------------------------------
    def clipboard_read(self) -> dict[str, Any]:
        if not IS_WINDOWS:
            return {"success": False, "error": "Disponível apenas no Windows"}
        completed = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"], capture_output=True, text=True, timeout=10)
        text = completed.stdout.strip()
        return {"message": f"Na área de transferência: {text[:500]}" if text else "A área de transferência está vazia.", "text": text}

    def clipboard_write(self, text: str) -> dict[str, Any]:
        if not IS_WINDOWS:
            return {"success": False, "error": "Disponível apenas no Windows"}
        subprocess.run(["powershell", "-NoProfile", "-Command", "$input | Set-Clipboard"], input=text, text=True, timeout=10, check=True)
        return {"message": "Copiei para a área de transferência.", "chars": len(text)}

    # sistema -------------------------------------------------------------------
    def lock_screen(self) -> dict[str, Any]:
        if not IS_WINDOWS:
            return {"success": False, "error": "Disponível apenas no Windows"}
        subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
        return {"message": "Tela bloqueada."}

    def system_status(self) -> dict[str, Any]:
        status: dict[str, Any] = {}
        root = Path(os.environ.get("SystemDrive", "C:") + "\\") if IS_WINDOWS else Path("/")
        usage = shutil.disk_usage(root)
        status["disk_free_gb"] = round(usage.free / 1024**3, 1)
        status["disk_used_percent"] = round(usage.used / usage.total * 100)
        status.update(_memory_and_battery())
        status["cpu_percent"] = _cpu_percent()
        parts = []
        if status.get("cpu_percent") is not None:
            parts.append(f"CPU em {status['cpu_percent']}%")
        if status.get("ram_percent") is not None:
            parts.append(f"memória em {status['ram_percent']}%")
        parts.append(f"{status['disk_free_gb']} GB livres no disco")
        if status.get("battery_percent") is not None:
            parts.append(f"bateria em {status['battery_percent']}%" + (" carregando" if status.get("charging") else ""))
        return {"message": ", ".join(parts).capitalize() + ".", **status}

    # arquivos, pastas e atalhos ---------------------------------------------------
    def open_folder(self, name: str) -> dict[str, Any]:
        key = name.casefold().strip()
        if key in KNOWN_FOLDERS:
            target = Path.home() / KNOWN_FOLDERS[key]
        else:
            target = Path(name).expanduser()
        if not target.exists():
            return {"success": False, "error": f"Pasta não encontrada: {target}"}
        self.open_target(str(target))
        return {"message": f"Abri {target.name or target}.", "path": str(target)}

    def find_files(self, name: str, folder: str = "~", limit: int = 20) -> dict[str, Any]:
        base = Path(folder).expanduser()
        if not base.is_dir():
            return {"success": False, "error": f"Pasta não encontrada: {base}"}
        needle = name.casefold().strip()
        found: list[str] = []
        deadline = time.monotonic() + 8
        skip = {"appdata", "node_modules", ".git", ".venv", "$recycle.bin", "windows", "program files"}
        for current, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d.casefold() not in skip and not d.startswith(".")]
            for file in files:
                if needle in file.casefold():
                    found.append(str(Path(current) / file))
                    if len(found) >= limit:
                        break
            if len(found) >= limit or time.monotonic() > deadline:
                break
        if not found:
            return {"message": f"Não encontrei arquivos com '{name}'.", "files": []}
        return {"message": f"Encontrei {len(found)} arquivo(s):\n" + "\n".join(found), "files": found}

    def youtube(self, query: str) -> dict[str, Any]:
        url = "https://www.youtube.com/results?" + urllib.parse.urlencode({"search_query": query})
        self.open_target(url)
        return {"message": f"Abri o YouTube com '{query}'.", "url": url}

    def spotify(self, query: str) -> dict[str, Any]:
        uri = "spotify:search:" + urllib.parse.quote(query)
        try:
            self.open_target(uri)
        except OSError:
            uri = "https://open.spotify.com/search/" + urllib.parse.quote(query)
            self.open_target(uri)
        return {"message": f"Procurei '{query}' no Spotify.", "uri": uri}

    def maps(self, destination: str) -> dict[str, Any]:
        url = "https://www.google.com/maps/search/?" + urllib.parse.urlencode({"api": 1, "query": destination})
        self.open_target(url)
        return {"message": f"Abri o mapa para {destination}.", "url": url}

    # registro --------------------------------------------------------------------
    SPECS: list[tuple[str, str, tuple[str, ...], dict[str, Any]]] = [
        ("current_time", "Data, hora e dia da semana atuais", (), {}),
        ("weather", "Clima atual e previsão de hoje de uma cidade (padrão: cidade do Du)", (), {"city": str}),
        ("calculate", "Calcula uma expressão matemática (ex.: '2*(3+4)', 'sqrt(81)', '15% de 200' como '0.15*200')", ("expression",), {"expression": str}),
        ("note_add", "Guarda uma anotação do Du", ("text",), {"text": str}),
        ("notes_list", "Lista as anotações do Du", (), {}),
        ("note_delete", "Apaga a anotação de número indicado", ("index",), {"index": int}),
        ("timer_set", "Cria um timer/lembrete em segundos; avisa por voz quando terminar", ("seconds",), {"seconds": (int, float), "label": str}),
        ("timers_list", "Lista timers ativos e o tempo restante", (), {}),
        ("timer_cancel", "Cancela um timer pelo id (ou todos, sem id)", (), {"id": str}),
        ("media", "Controla a mídia do Windows (Spotify, YouTube...): play_pause, next, previous, stop, mute", ("action",), {"action": str}),
        ("volume", "Ajusta o volume do Windows: up, down ou mute", ("direction",), {"direction": str, "steps": int}),
        ("clipboard_read", "Lê o texto da área de transferência", (), {}),
        ("clipboard_write", "Copia um texto para a área de transferência", ("text",), {"text": str}),
        ("lock_screen", "Bloqueia a tela do Windows", (), {}),
        ("system_status", "CPU, memória, disco e bateria do computador", (), {}),
        ("open_folder", "Abre uma pasta (downloads, documentos, área de trabalho, imagens, músicas, vídeos ou um caminho)", ("name",), {"name": str}),
        ("find_files", "Procura arquivos pelo nome numa pasta (padrão: pasta pessoal)", ("name",), {"name": str, "folder": str, "limit": int}),
        ("youtube", "Pesquisa e abre resultados no YouTube", ("query",), {"query": str}),
        ("spotify", "Pesquisa uma música, artista ou playlist no Spotify", ("query",), {"query": str}),
        ("maps", "Abre o Google Maps para um local ou rota", ("destination",), {"destination": str}),
    ]

    def register(self, executor: Any, schemas: Any | None = None) -> None:
        from brain.tool_schema import ToolSpec

        for name, description, required, types in self.SPECS:
            executor.register(name, getattr(self, name))
            if schemas is not None:
                schemas.register(ToolSpec(name, description, required, types))


def _memory_and_battery() -> dict[str, Any]:
    if not IS_WINDOWS:
        try:
            info = Path("/proc/meminfo").read_text().split("\n")
            values = {line.split(":")[0]: int(line.split()[1]) for line in info if ":" in line and len(line.split()) > 1}
            return {"ram_percent": round((1 - values["MemAvailable"] / values["MemTotal"]) * 100)}
        except Exception:
            return {}
    import ctypes

    class MemoryStatus(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    class PowerStatus(ctypes.Structure):
        _fields_ = [("ACLineStatus", ctypes.c_byte), ("BatteryFlag", ctypes.c_byte), ("BatteryLifePercent", ctypes.c_byte),
                    ("SystemStatusFlag", ctypes.c_byte), ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]

    result: dict[str, Any] = {}
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    memory = MemoryStatus()
    memory.dwLength = ctypes.sizeof(MemoryStatus)
    if kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
        result["ram_percent"] = int(memory.dwMemoryLoad)
    power = PowerStatus()
    if kernel32.GetSystemPowerStatus(ctypes.byref(power)) and power.BatteryLifePercent != -1 and (power.BatteryFlag & 128) == 0:
        result["battery_percent"] = int(power.BatteryLifePercent) & 0xFF
        result["charging"] = power.ACLineStatus == 1
    return result


def _cpu_percent(interval: float = 0.3) -> int | None:
    if not IS_WINDOWS:
        try:
            return round(getattr(os, "getloadavg")()[0] / (os.cpu_count() or 1) * 100)
        except (OSError, AttributeError):
            return None
    import ctypes

    def times() -> tuple[int, int, int]:
        idle, kernel, user = (ctypes.c_ulonglong() for _ in range(3))
        ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))  # type: ignore[attr-defined]
        return idle.value, kernel.value, user.value

    idle1, kernel1, user1 = times()
    time.sleep(interval)
    idle2, kernel2, user2 = times()
    total = (kernel2 - kernel1) + (user2 - user1)
    if total <= 0:
        return None
    return round((1 - (idle2 - idle1) / total) * 100)
