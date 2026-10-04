from __future__ import annotations

import importlib.util
import os
import platform
from functools import lru_cache

from brain.vision import OpenAIResponsesVisionAdapter

from .composite_analyzer import CompositeScreenAnalyzer
from .model_vision_analyzer import ModelVisionAnalyzer
from .perception import Perception, ScreenAnalyzer
from .ui import UIController
from .ui_tools import UITools
from .verification import Verification
from .windows_perception import WindowsScreenBackend
from .windows_screen_analyzer import WindowsScreenAnalyzer
from .windows_ui import WindowsUIController, ensure_dpi_awareness


def _model_vision_enabled() -> bool:
    return os.getenv("DUQUE_ENABLE_MODEL_VISION", "0").casefold() in {"1", "true", "yes", "on"}


def _screen_analyzer() -> ScreenAnalyzer:
    local = WindowsScreenAnalyzer()
    if not _model_vision_enabled():
        return local
    try:
        vision = ModelVisionAnalyzer(adapter=OpenAIResponsesVisionAdapter())
    except Exception as exc:
        vision = ModelVisionAnalyzer(unavailable_reason=f"{type(exc).__name__}: {exc}")
    return CompositeScreenAnalyzer(local, vision)


def _screen_capture_available() -> bool:
    return platform.system() == "Windows" and importlib.util.find_spec("PIL") is not None


@lru_cache(maxsize=1)
def shared_perception() -> Perception | None:
    """Pilha única de percepção (captura + OCR + visão) usada por UI e verificação.

    Sem Windows ou sem Pillow não há captura de tela: devolve None em vez de
    criar ferramentas que falhariam em toda chamada.
    """
    if not _screen_capture_available():
        return None
    ensure_dpi_awareness()
    return Perception(WindowsScreenBackend(), analyzer=_screen_analyzer())


def create_ui_tools() -> UITools:
    """Monta o conjunto real de UI/percepção quando executado no Windows."""
    if platform.system() != "Windows":
        return UITools()
    controller: UIController = WindowsUIController()
    return UITools(controller=controller, perception=shared_perception())


def create_verification() -> Verification | None:
    """Cria verificação visual real no Windows, sobre a percepção compartilhada."""
    perception = shared_perception()
    if perception is None:
        return None
    return Verification(perception)
