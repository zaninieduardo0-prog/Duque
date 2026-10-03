"""Clicar no que se vê: "clique no botão Enviar", "clique no campo de busca".

O modelo de visão recebe o print da tela com uma grade numerada e devolve a
posição do elemento em frações (0–1). Para precisão, faz duas passadas: uma
na tela inteira e outra num recorte ampliado em volta do primeiro palpite.
Depois do clique, o TELEX olha a tela de novo (evidência, não suposição).

Com o processo "ciente de DPI" (duque.py), os pixels do print são os mesmos
do mouse, mesmo com a escala do Windows em 125%/150%.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable

LOCATE_PROMPT = (
    "Esta é a tela do computador do Du (ou um recorte ampliado dela), com uma grade de referência: "
    "as linhas finas marcam cada 10% da largura (números em cima) e da altura (números à esquerda). "
    "Encontre o elemento descrito: \"{target}\". "
    "Responda SOMENTE JSON: {{\"found\": true, \"x\": <0 a 1>, \"y\": <0 a 1>, \"what\": \"o que você achou\"}} "
    "com o CENTRO do elemento em frações da largura e da altura desta imagem, "
    "ou {{\"found\": false, \"why\": \"motivo\"}} se não estiver visível."
)


def draw_grid(image: Any) -> Any:
    """Cópia da imagem com grade a cada 10% e rótulos (ajuda o modelo a dar coordenadas)."""
    from PIL import ImageDraw

    copy = image.convert("RGB").copy()
    draw = ImageDraw.Draw(copy)
    width, height = copy.size
    for step in range(1, 10):
        x, y = width * step // 10, height * step // 10
        draw.line([(x, 0), (x, height)], fill=(255, 0, 255), width=1)
        draw.line([(0, y), (width, y)], fill=(255, 0, 255), width=1)
        draw.text((x + 2, 2), str(step * 10), fill=(255, 0, 255))
        draw.text((2, y + 2), str(step * 10), fill=(255, 0, 255))
    return copy


def parse_point(text: str) -> tuple[float, float] | None:
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group())
    except ValueError:
        return None
    if not data.get("found"):
        return None
    try:
        x, y = float(data["x"]), float(data["y"])
    except (KeyError, TypeError, ValueError):
        return None
    if x > 1.0 or y > 1.0:  # veio em porcentagem
        x, y = x / 100.0, y / 100.0
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        return None
    return x, y


class ScreenPointer:
    def __init__(
        self,
        capture: Callable[[], Any],
        analyze: Callable[[Any, str], str],
        click: Callable[[int, int], Any],
        *,
        double_click: Callable[[int, int], Any] | None = None,
        limit: int = 1280,
    ) -> None:
        self.capture = capture
        self.analyze = analyze
        self.click = click
        self.double_click = double_click
        self.limit = limit

    def _ask(self, image: Any, target: str) -> tuple[float, float] | None:
        small = image.copy()
        small.thumbnail((self.limit, self.limit))
        return parse_point(self.analyze(draw_grid(small), LOCATE_PROMPT.format(target=target)))

    def locate(self, target: str) -> tuple[int, int] | None:
        screen = self.capture()
        width, height = screen.size
        first = self._ask(screen, target)
        if first is None:
            return None
        x, y = first[0] * width, first[1] * height
        # Segunda passada: recorte de 30% em volta do palpite, ampliado.
        half_w, half_h = width * 0.15, height * 0.15
        left, top = max(0, int(x - half_w)), max(0, int(y - half_h))
        right, bottom = min(width, int(x + half_w)), min(height, int(y + half_h))
        if right - left > 40 and bottom - top > 40:
            second = self._ask(screen.crop((left, top, right, bottom)), target)
            if second is not None:
                x = left + second[0] * (right - left)
                y = top + second[1] * (bottom - top)
        return int(round(x)), int(round(y))

    def click_on(self, target: str, double: bool = False) -> dict[str, Any]:
        target = (target or "").strip()
        if not target:
            return {"success": False, "error": "Diga em que clicar."}
        try:
            point = self.locate(target)
        except Exception as exc:
            return {"success": False, "error": f"Não consegui olhar a tela: {type(exc).__name__}: {exc}"}
        if point is None:
            return {"success": False, "error": f"Não encontrei '{target}' na tela."}
        if double and self.double_click is not None:
            self.double_click(*point)
        else:
            self.click(*point)
        return {"message": f"Cliquei em '{target}' ({point[0]}, {point[1]}).", "x": point[0], "y": point[1]}


def default_pointer(controller: Any) -> ScreenPointer | None:
    """Ponteiro real (Windows + OpenAI); None quando não há como enxergar a tela."""
    if not os.getenv("OPENAI_API_KEY"):
        return None
    from brain.vision import OpenAIResponsesVisionAdapter

    from .screen_vision import _default_capture

    adapter = OpenAIResponsesVisionAdapter(model=os.getenv("DUQUE_POINTER_MODEL") or "gpt-4o")

    def analyze(image: Any, prompt: str) -> str:
        return str(getattr(adapter.analyze(image, prompt), "text", "") or "")

    def double(x: int, y: int) -> None:
        controller.click(x, y)
        controller.click(x, y)

    return ScreenPointer(_default_capture, analyze, controller.click, double_click=double)
