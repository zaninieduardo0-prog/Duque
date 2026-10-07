"""Ferramentas do PC: tela + mouse (quando não há jeito melhor), Bloco de Notas e programas."""

from __future__ import annotations

import io
import os
import platform
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

IS_WINDOWS = platform.system() == "Windows"
SCREEN_WIDTH = 1280  # a captura vai reduzida para a IA; os cliques voltam para a escala real


class Screen:
    """Captura a tela e clica em coordenadas da captura (convertidas para a tela real)."""

    def __init__(self, controller: Any = None) -> None:
        self._controller = controller
        self.scale = 1.0

    @property
    def controller(self) -> Any:
        if self._controller is None:
            if not IS_WINDOWS:
                raise RuntimeError("Controle de mouse e teclado só funciona no Windows.")
            from computer.windows_ui import WindowsUIController

            self._controller = WindowsUIController()
        return self._controller

    def capture(self) -> tuple[bytes, str]:
        from PIL import ImageGrab

        image = ImageGrab.grab(all_screens=False)
        width, height = image.size
        self.scale = width / SCREEN_WIDTH if width > SCREEN_WIDTH else 1.0
        if self.scale != 1.0:
            image = image.resize((SCREEN_WIDTH, round(height / self.scale)))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        shown = image.size
        return buffer.getvalue(), f"Tela capturada ({shown[0]}x{shown[1]}). Use essas coordenadas para clicar."

    def click(self, x: int, y: int, double: bool = False, button: str = "left") -> str:
        real_x, real_y = round(int(x) * self.scale), round(int(y) * self.scale)
        self.controller.click(real_x, real_y, button=button)
        if double:
            time.sleep(0.05)
            self.controller.click(real_x, real_y, button=button)
        time.sleep(0.4)
        return f"Cliquei em ({x}, {y}). Capture a tela de novo para conferir."

    def type_text(self, text: str) -> str:
        self.controller.type_text(text)
        return "Digitei o texto na janela em foco."

    def keys(self, combo: str) -> str:
        parts = [part.strip() for part in re.split(r"[+ ]+", combo or "") if part.strip()]
        if not parts:
            raise ValueError("Diga a tecla (ex.: enter, ctrl+c, alt+tab).")
        if len(parts) == 1:
            self.controller.press(parts[0])
        else:
            self.controller.hotkey(*parts)
        return f"Apertei {combo}."


def notepad(text: str, title: str = "") -> dict[str, Any]:
    """Escreve o texto num arquivo .txt (Documentos\\TELEX) e abre no Bloco de Notas.

    Gravar no arquivo e abrir é confiável; digitar numa janela do Bloco de
    Notas dependia do foco (e às vezes o texto ia para outra janela).
    """
    from computer.file_tools import known_folder, sanitize_filename

    content = (text or "").strip("\n")
    if not content.strip():
        raise ValueError("Não tenho o que escrever.")
    folder = (known_folder("documentos") or Path.home() / "Documents") / "TELEX"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
    name = sanitize_filename(f"{title.strip()} {stamp}" if title.strip() else f"nota {stamp}", ".txt")
    path = folder / name
    path.write_text(content.replace("\n", os.linesep) if IS_WINDOWS else content, encoding="utf-8")
    if IS_WINDOWS:
        subprocess.Popen(["notepad.exe", str(path)], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return {"ok": True, "arquivo": str(path), "aberto_no_bloco_de_notas": IS_WINDOWS}
