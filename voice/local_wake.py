"""Ativação local do TELEX, sem internet e sem API.

Um reconhecedor de fala em português (Vosk) roda no microfone em standby,
mas preso a uma gramática com poucas frases. Ele não transcreve conversa:
só decide se ouviu exatamente uma destas:

- "Bom dia / Boa tarde / Boa noite, TELEX" → acorda (conversa de voz)
- "Repousar TELEX"                         → volta ao standby
- "Retomar TELEX"                          → sai da pausa de emergência

O modelo (~50 MB) fica em ``duque_data/modelos/vosk-pt`` e é baixado pelo
``preparar_duque.bat`` (``python -m voice.local_wake --baixar``). Sem o modelo
ou sem o pacote ``vosk``, o TELEX continua acordando com "Hey Jarvis".
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import unicodedata
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

ROOT = Path(__file__).resolve().parent.parent
MODEL_URL = os.getenv(
    "DUQUE_VOSK_URL", "https://alphacephei.com/vosk/models/vosk-model-small-pt-0.3.zip"
)
DEFAULT_MODEL_DIR = ROOT / "duque_data" / "modelos" / "vosk-pt"
SAMPLE_RATE = 16000

Kind = Literal["wake", "sleep", "resume"]

# Como o nome pode estar escrito no vocabulário do modelo. Só entram na
# gramática as grafias que o modelo conhece (Model.find_word).
NAME_SPELLINGS = ("telex", "télex", "teles", "telecs", "teleks")
WAKE_PREFIXES = ("bom dia", "boa tarde", "boa noite")
COMMANDS: dict[str, Kind] = {
    **{prefix: "wake" for prefix in WAKE_PREFIXES},
    "repousar": "sleep",
    "retomar": "resume",
}


def plain(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", (text or "").casefold())
    no_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", no_accents))


_PLAIN_NAMES = frozenset(plain(name) for name in NAME_SPELLINGS)


@dataclass(slots=True, frozen=True)
class Heard:
    kind: Kind
    phrase: str

    @property
    def greeting(self) -> str:
        """Saudação para a conversa ("Bom dia, TELEX.")."""
        words = self.phrase.split()
        return (" ".join(words[:-1]).capitalize() + ", TELEX.") if len(words) > 1 else "TELEX."


def classify(text: str) -> Heard | None:
    """Frase exata (com o nome no fim) → o que fazer. Qualquer outra coisa → None."""
    words = plain(text).split()
    if len(words) < 2 or words[-1] not in _PLAIN_NAMES:
        return None
    command = " ".join(words[:-1])
    kind = COMMANDS.get(command)
    return Heard(kind, f"{command} telex") if kind else None


def decide(heard: Heard | None, jarvis: bool, paused: bool) -> tuple[str, str | None]:
    """O que o laço de standby faz: ("wake", saudação), ("resume", None) ou ("none", None).

    Em pausa de emergência, só "Retomar, TELEX" é atendido; acordar não.
    """
    if heard is not None and heard.kind == "resume":
        return ("resume", None) if paused else ("none", None)
    if paused:
        return ("none", None)
    if heard is not None and heard.kind == "wake":
        return ("wake", heard.greeting)
    if jarvis:
        return ("wake", None)
    return ("none", None)


def grammar(known: Callable[[str], bool] | None = None) -> list[str]:
    """Frases aceitas pelo reconhecedor (+ "[unk]" para todo o resto)."""
    names = [name for name in NAME_SPELLINGS if known is None or known(name)]
    phrases = [f"{command} {name}" for command in COMMANDS for name in names]
    return phrases + ["[unk]"]


def find_model(path: str | Path | None = None) -> Path | None:
    candidate = Path(path or os.getenv("DUQUE_VOSK_MODEL") or DEFAULT_MODEL_DIR)
    if (candidate / "am").is_dir() or (candidate / "conf").is_dir():
        return candidate
    # Zip extraído com a pasta interna (vosk-model-small-pt-0.3/...).
    if candidate.is_dir():
        for child in sorted(candidate.iterdir()):
            if child.is_dir() and ((child / "am").is_dir() or (child / "conf").is_dir()):
                return child
    return None


class LocalWake:
    """Recebe áudio 16 kHz mono int16 (os frames do PvRecorder) e avisa as frases."""

    def __init__(self, model: Any, recognizer_factory: Callable[[Any, float, str], Any]) -> None:
        self.model = model
        self.phrases = grammar(self._knows if hasattr(model, "find_word") else None)
        if len(self.phrases) <= 1:
            raise RuntimeError("o modelo não conhece nenhuma grafia de 'telex'")
        self._factory = recognizer_factory
        self._recognizer = recognizer_factory(model, SAMPLE_RATE, json.dumps(self.phrases))

    def _knows(self, word: str) -> bool:
        index: Any = self.model.find_word(word)
        return int(index) >= 0

    @property
    def names(self) -> list[str]:
        return sorted({phrase.split()[-1] for phrase in self.phrases if phrase != "[unk]"})

    def reset(self) -> None:
        try:
            self._recognizer.Reset()
        except Exception:
            self._recognizer = self._factory(self.model, SAMPLE_RATE, json.dumps(self.phrases))

    def feed(self, pcm: bytes) -> Heard | None:
        recognizer = self._recognizer
        if recognizer.AcceptWaveform(pcm):
            text = _field(recognizer.Result(), "text")
        else:
            # A frase completa já aparece no parcial: responde sem esperar o silêncio.
            text = _field(recognizer.PartialResult(), "partial")
        heard = classify(text)
        if heard is not None:
            self.reset()
        return heard


def _field(raw: str, key: str) -> str:
    try:
        value = json.loads(raw or "{}").get(key, "")
    except ValueError:
        return ""
    return value if isinstance(value, str) else ""


def load(log: Callable[[str], Any] = print) -> LocalWake | None:
    """Carrega o reconhecedor local; None (com o motivo no log) se não der."""
    if os.getenv("DUQUE_LOCAL_WAKE", "1").casefold() in {"0", "false", "off", "no", "nao", "não"}:
        log("[WAKE] ativação local desligada (DUQUE_LOCAL_WAKE=0).")
        return None
    model_dir = find_model()
    if model_dir is None:
        log(f"[WAKE] modelo de português não encontrado em {DEFAULT_MODEL_DIR}; rode o preparar_duque.bat.")
        return None
    try:
        import vosk  # type: ignore[import-not-found]

        vosk.SetLogLevel(-1)
        listener = LocalWake(vosk.Model(str(model_dir)), vosk.KaldiRecognizer)
    except Exception as exc:
        log(f"[WAKE] ativação local indisponível: {type(exc).__name__}: {exc}")
        return None
    log(f"[WAKE] ativação local pronta ({model_dir.name}); nome reconhecido como {listener.names}.")
    return listener


def download(target: Path = DEFAULT_MODEL_DIR, url: str = MODEL_URL) -> Path:
    """Baixa e extrai o modelo de português (uma vez só)."""
    found = find_model(target)
    if found is not None:
        print(f"Modelo de ativação já instalado: {found}")
        return found
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"Baixando o modelo de ativação do TELEX (~50 MB)...\n  {url}")
    with tempfile.TemporaryDirectory(dir=target.parent) as tmp:
        archive = Path(tmp) / "modelo.zip"
        with urllib.request.urlopen(url, timeout=60) as response, archive.open("wb") as out:
            shutil.copyfileobj(response, out)
        extracted = Path(tmp) / "extraido"
        with zipfile.ZipFile(archive) as zipped:
            zipped.extractall(extracted)
        inner = find_model(extracted)
        if inner is None:
            raise RuntimeError("o arquivo baixado não parece um modelo Vosk")
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(inner), str(target))
    print(f"Modelo instalado em {target}")
    return target


if __name__ == "__main__":
    if "--baixar" in sys.argv:
        try:
            download()
        except Exception as exc:
            print(f"[AVISO] Não consegui baixar o modelo de ativação: {exc}")
            print('        O TELEX continua acordando com "Hey Jarvis".')
    else:
        print(__doc__)
