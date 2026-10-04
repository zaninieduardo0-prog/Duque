"""Ativação local do TELEX, sem internet e sem API.

Um reconhecedor de fala em português (Vosk) roda no microfone em standby,
mas preso a uma gramática com poucas frases. Ele não transcreve conversa:
só decide se ouviu exatamente uma destas:

- "Bom dia / Boa tarde / Boa noite, TELEX" → acorda (conversa de voz)
- "Repousar TELEX"                         → volta ao standby
- "Retomar TELEX"                          → sai da pausa de emergência
- "TELEX" (sozinho ou no começo da frase)   → abre a escuta (o áudio já dito vai junto)

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

Kind = Literal["wake", "sleep", "resume", "call"]

# Como o nome pode estar escrito no vocabulário do modelo. Só entram na
# gramática as grafias que o modelo conhece (Model.find_word).
NAME_SPELLINGS = ("telex", "télex", "teles", "telecs", "teleks")
WAKE_PREFIXES = ("bom dia", "boa tarde", "boa noite")
COMMANDS: dict[str, Kind] = {
    **{prefix: "wake" for prefix in WAKE_PREFIXES},
    "repousar": "sleep",
    "retomar": "resume",
}
# Ganho automático para microfones baixos (pico ~0.1): nunca passa deste fator.
MAX_GAIN = float(os.getenv("DUQUE_WAKE_MAX_GAIN", "6"))
TARGET_PEAK = 0.30


def plain(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", (text or "").casefold())
    no_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    no_accents = re.sub(r"\btele[\s-]+(x|xis|ex|cs|ks|es)\b", "telex", no_accents)
    return " ".join(re.findall(r"[a-z0-9]+", no_accents))


# Modo livre (modelo sem a palavra "telex" no vocabulário): aceita o que soar
# parecido — "teles", "telê", "telecs", "tele"...
_LOOSE_NAME = re.compile(r"tele[a-z]{0,4}|tel[ei]?[ckx]s?|tel[ée]")
# Palavras comuns que o padrão livre confundia com o nome ("telefone tocou" acordava o TELEX).
_NOT_NAMES = frozenset({
    "telefone", "telefones", "telefona", "telefonar", "telefonou", "telefonei", "telefonia",
    "telefonema", "teleco", "telha", "telhas", "telas", "telado", "teleton",
})


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


def _is_name(word: str, loose: bool) -> bool:
    return word in _PLAIN_NAMES or (loose and word not in _NOT_NAMES and bool(_LOOSE_NAME.fullmatch(word)))


def classify(text: str, *, loose: bool = False) -> Heard | None:
    """Frase exata (com o nome no fim) → o que fazer. Qualquer outra coisa → None.

    No modo livre, a frase pode vir no fim de uma fala maior ("ok, bom dia telê").
    """
    words = [word for word in plain(text).split() if word != "unk"]
    if words and _is_name(words[0], loose):
        rest = " ".join(words[1:])
        if COMMANDS.get(rest) == "wake":  # "Telex, boa tarde" (nome primeiro)
            return Heard("wake", f"{rest} telex")
        if len(words) == 1 or not COMMANDS.get(" ".join(words[:-1])):
            return Heard("call", "telex")
    if len(words) < 2 or not _is_name(words[-1], loose):
        return None
    candidates = [" ".join(words[:-1])]
    if loose:
        candidates += [" ".join(words[-3:-1]), " ".join(words[-2:-1])]
    for command in candidates:
        kind = COMMANDS.get(command)
        if kind:
            return Heard(kind, f"{command} telex")
    return None


def decide(heard: Heard | None, jarvis: bool, paused: bool) -> tuple[str, str | None]:
    """O que o laço de standby faz: ("wake", saudação), ("call", None), ("resume", None) ou ("none", None).

    Em pausa de emergência, só "Retomar, TELEX" é atendido; acordar não.
    """
    if heard is not None and heard.kind == "resume":
        return ("resume", None) if paused else ("none", None)
    if paused:
        return ("none", None)
    if heard is not None and heard.kind == "wake":
        return ("wake", heard.greeting)
    if heard is not None and heard.kind == "call":
        return ("call", None)
    if jarvis:
        return ("wake", None)
    return ("none", None)


def grammar(known: Callable[[str], bool] | None = None) -> list[str]:
    """Frases aceitas pelo reconhecedor (+ "[unk]" para todo o resto)."""
    names = [name for name in NAME_SPELLINGS if known is None or known(name)]
    phrases = [f"{command} {name}" for command in COMMANDS for name in names]
    phrases += [f"{name} {prefix}" for name in names for prefix in WAKE_PREFIXES] + names
    return phrases + ["[unk]"]


def boost(pcm: bytes, peak_seen: float) -> tuple[bytes, float]:
    """Amplifica áudio baixo (int16) até um pico razoável; devolve (áudio, pico lembrado).

    O pico lembrado cai devagar, então um microfone baixo é amplificado de forma
    estável e um barulho forte não deixa o ganho em 1 para sempre.
    """
    import array

    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - len(pcm) % 2])
    if not samples:
        return pcm, peak_seen
    frame_peak = max(max(samples), -min(samples)) / 32768.0
    peak_seen = max(frame_peak, peak_seen * 0.995)
    if peak_seen < 0.01:  # silêncio: amplificar só levanta ruído
        return pcm, peak_seen
    gain = min(MAX_GAIN, TARGET_PEAK / peak_seen)
    if gain <= 1.05:
        return pcm, peak_seen
    boosted = array.array("h", (max(-32768, min(32767, int(sample * gain))) for sample in samples))
    return boosted.tobytes(), peak_seen


def is_model_dir(path: Path) -> bool:
    """Modelos novos têm am/ e conf/; os antigos (como o small-pt-0.3) têm os arquivos soltos."""
    if (path / "am").is_dir() or (path / "conf").is_dir():
        return True
    return any((path / name).is_file() for name in ("final.mdl", "mfcc.conf", "HCLr.fst", "Gr.fst"))


def find_model(path: str | Path | None = None) -> Path | None:
    candidate = Path(path or os.getenv("DUQUE_VOSK_MODEL") or DEFAULT_MODEL_DIR)
    if not candidate.is_dir():
        return None
    if is_model_dir(candidate):
        return candidate
    # Zip extraído com uma ou duas pastas por cima (vosk-model-small-pt-0.3/...).
    for child in sorted(p for p in candidate.iterdir() if p.is_dir()):
        if is_model_dir(child):
            return child
        for grandchild in sorted(p for p in child.iterdir() if p.is_dir()):
            if is_model_dir(grandchild):
                return grandchild
    return None


class LocalWake:
    """Recebe áudio 16 kHz mono int16 (os frames do PvRecorder) e avisa as frases."""

    def __init__(self, model: Any, recognizer_factory: Callable[..., Any]) -> None:
        self.model = model
        self.phrases = grammar(self._knows if hasattr(model, "find_word") else None)
        # Sem nenhuma grafia de "telex" no vocabulário, a gramática não serviria:
        # o reconhecedor ouve livre e a frase é conferida com o nome aproximado.
        self.loose = len(self.phrases) <= 1
        if self.loose:
            self.phrases = []
        self._factory = recognizer_factory
        self._peak = 0.0
        self._recognizer = self._new_recognizer()

    def _new_recognizer(self) -> Any:
        if self.loose:
            return self._factory(self.model, SAMPLE_RATE)
        return self._factory(self.model, SAMPLE_RATE, json.dumps(self.phrases))

    def _knows(self, word: str) -> bool:
        try:
            index: Any = self.model.find_word(word)
            return int(index) >= 0
        except Exception:
            return False

    @property
    def names(self) -> list[str]:
        if self.loose:
            return ["modo livre (nome aproximado)"]
        spellings = {plain(name) for name in NAME_SPELLINGS}
        return sorted({word for phrase in self.phrases for word in phrase.split() if plain(word) in spellings})

    def reset(self) -> None:
        try:
            self._recognizer.Reset()
        except Exception:
            self._recognizer = self._new_recognizer()

    def feed(self, pcm: bytes) -> Heard | None:
        recognizer = self._recognizer
        pcm, self._peak = boost(pcm, self._peak)
        if recognizer.AcceptWaveform(pcm):
            text = _field(recognizer.Result(), "text")
        else:
            # A frase completa já aparece no parcial: responde sem esperar o silêncio.
            text = _field(recognizer.PartialResult(), "partial")
        heard = classify(text, loose=self.loose)
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
            found = sorted(str(p.relative_to(extracted)) for p in extracted.rglob("*"))[:12]
            raise RuntimeError(f"o arquivo baixado não parece um modelo Vosk (conteúdo: {found})")
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
