from __future__ import annotations

import os
import platform

from brain.vision import NullVisionAdapter, OpenAIResponsesVisionAdapter

from .composite_analyzer import CompositeScreenAnalyzer
from .model_vision_analyzer import ModelVisionAnalyzer
from .perception import Perception
from .ui import UIController
from .ui_backend import WindowsUIController
from .ui_tools import UITools
from .verification import Verification
from .windows_perception import WindowsScreenBackend
from .windows_screen_analyzer import WindowsScreenAnalyzer


def _create_analyzer() -> CompositeScreenAnalyzer:
    local = WindowsScreenAnalyzer()
    if os.getenv("DUQUE_ENABLE_MODEL_VISION", "0").casefold() not in {"1", "true", "yes", "on"}:
        vision = ModelVisionAnalyzer(NullVisionAdapter())
    else:
        try:
            vision = ModelVisionAnalyzer(OpenAIResponsesVisionAdapter())
        except ValueError:
            # Configuração incompleta nunca deve impedir o Duque de iniciar.
            vision = ModelVisionAnalyzer(NullVisionAdapter())
    return CompositeScreenAnalyzer(local, vision)


def create_ui_tools() -> UITools:
    """Monta o conjunto real de UI/percepção quando executado no Windows."""
    if platform.system() != "Windows":
        return UITools()
    controller: UIController = WindowsUIController()
    perception = Perception(WindowsScreenBackend(), analyzer=_create_analyzer())
    return UITools(controller=controller, perception=perception)


def create_verification() -> Verification | None:
    """Cria percepção/verificação visual real no Windows."""
    if platform.system() != "Windows":
        return None
    perception = Perception(WindowsScreenBackend(), analyzer=_create_analyzer())
    return Verification(perception)
