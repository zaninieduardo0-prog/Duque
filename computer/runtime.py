from __future__ import annotations

import os
import platform

from brain.vision import NullVisionAdapter, OpenAIResponsesVisionAdapter

from .composite_analyzer import CompositeScreenAnalyzer
from .perception import Perception
from .ui import UIController
from .ui_tools import UITools
from .verification import Verification
from .windows_perception import WindowsScreenBackend
from .windows_screen_analyzer import WindowsScreenAnalyzer
from .windows_ui import WindowsUIController
from .model_vision_analyzer import ModelVisionAnalyzer


def _model_vision_enabled() -> bool:
    return os.getenv("DUQUE_ENABLE_MODEL_VISION", "0").casefold() in {"1", "true", "yes", "on"}


def _screen_analyzer():
    local = WindowsScreenAnalyzer()
    if not _model_vision_enabled():
        return local
    try:
        vision = ModelVisionAnalyzer(adapter=OpenAIResponsesVisionAdapter())
    except Exception:
        vision = ModelVisionAnalyzer(adapter=NullVisionAdapter())
    return CompositeScreenAnalyzer(local, vision)


def create_ui_tools() -> UITools:
    """Monta o conjunto real de UI/percepção quando executado no Windows."""
    if platform.system() != "Windows":
        return UITools()
    controller: UIController = WindowsUIController()
    perception = Perception(WindowsScreenBackend(), analyzer=_screen_analyzer())
    return UITools(controller=controller, perception=perception)


def create_verification() -> Verification | None:
    """Cria percepção/verificação visual real no Windows."""
    if platform.system() != "Windows":
        return None
    perception = Perception(WindowsScreenBackend(), analyzer=_screen_analyzer())
    return Verification(perception)
