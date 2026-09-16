from __future__ import annotations

import platform

from .ui import UIController


def create_ui_controller() -> UIController:
    """Cria o backend de UI apropriado para a máquina atual."""
    if platform.system() == "Windows":
        from .windows_ui import WindowsUIController

        return WindowsUIController()
    raise RuntimeError("Controle gráfico automático ainda não possui backend para este sistema")
