"""O que está tocando no Spotify (Windows), sem API nem login.

O aplicativo do Spotify usa o título da janela como "Artista - Música" enquanto
toca e "Spotify Premium"/"Spotify Free" quando está pausado. Lemos esse título
pelo `tasklist /v`, que já vem com o Windows.
"""

from __future__ import annotations

import csv
import io
import subprocess
import sys
import time
from typing import Any, Callable

IDLE_TITLES = {"spotify", "spotify premium", "spotify free"}
IGNORED_TITLES = {"", "n/a", "oleMainThreadWndName".casefold(), "msctfime ui", "default ime", "gdi+ window (spotify.exe)"}


def window_titles(tasklist_csv: str) -> list[str]:
    """Extrai os títulos de janela (última coluna) da saída CSV do tasklist /v."""
    titles: list[str] = []
    for row in csv.reader(io.StringIO(tasklist_csv)):
        if len(row) < 2:
            continue
        title = row[-1].strip()
        if title.casefold() not in IGNORED_TITLES:
            titles.append(title)
    return titles


def parse_spotify(titles: list[str], running: bool) -> dict[str, Any]:
    if not running:
        return {"running": False, "playing": False, "track": "", "artist": ""}
    for title in titles:
        if " - " in title and title.casefold() not in IDLE_TITLES:
            artist, track = title.split(" - ", 1)
            return {"running": True, "playing": True, "track": track.strip(), "artist": artist.strip()}
    return {"running": True, "playing": False, "track": "", "artist": ""}


def _tasklist() -> tuple[str, bool]:
    completed = subprocess.run(
        ["tasklist", "/v", "/fo", "csv", "/nh", "/fi", "imagename eq spotify.exe"],
        capture_output=True,
        text=True,
        timeout=10,
        shell=False,
    )
    output = completed.stdout
    running = "spotify.exe" in output.casefold()
    return output, running


class NowPlaying:
    def __init__(self, reader: Callable[[], tuple[str, bool]] | None = None, *, cache_seconds: float = 4.0) -> None:
        self.reader = reader or (_tasklist if sys.platform.startswith("win") else (lambda: ("", False)))
        self.cache_seconds = cache_seconds
        self._cached: dict[str, Any] | None = None
        self._at = 0.0

    def get(self) -> dict[str, Any]:
        now = time.monotonic()
        if self._cached is not None and now - self._at < self.cache_seconds:
            return self._cached
        try:
            output, running = self.reader()
            result = parse_spotify(window_titles(output), running)
        except Exception as exc:
            result = {"running": False, "playing": False, "track": "", "artist": "", "error": f"{type(exc).__name__}: {exc}"}
        self._cached, self._at = result, now
        return result

    def invalidate(self) -> None:
        self._cached = None
