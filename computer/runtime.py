from __future__ import annotations

import platform

from .perception import Perception
from .ui import UIController
from .ui_backend import WindowsUIController
from .ui_tools import UITools
from .windows_perception import WindowsScreenBackend


def create_ui_tools() -> UITools:
    """Monta o conjunto real de UI/percepção quando executado no Windows."""
    if platform.system() != "Windows":
        return UITools()
    controller: UIController = WindowsUIController()
    perception = Perception(WindowsScreenBackend())
    return UITools(controller=controller, perception=perception)
