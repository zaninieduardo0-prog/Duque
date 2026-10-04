"""Voz do TELEX no próprio PC, sem API.

Dois motores, escolhidos por DUQUE_TTS (auto | piper | sapi):

- **Piper** (neural, soa natural, funciona offline). É a voz "sua": qualquer
  arquivo ``.onnx`` de voz do Piper colocado em ``duque_data/vozes/`` vira uma
  voz do TELEX. Para trocar de voz, troque o arquivo (ou DUQUE_PIPER_VOICE).
- **SAPI** (as vozes do Windows, como "Microsoft Maria"). Não instala nada;
  serve de reserva quando o Piper ainda não foi instalado.

Em ``auto``: Piper se o executável e uma voz existirem, senão SAPI.
Variáveis: DUQUE_PIPER_EXE, DUQUE_PIPER_VOICE (caminho ou nome do arquivo),
DUQUE_SAPI_VOICE (parte do nome, ex. "Maria"), DUQUE_TTS_RATE (-10..10, SAPI).
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
VOICES_DIR = ROOT / "duque_data" / "vozes"
PIPER_DIR = ROOT / "duque_data" / "piper"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass(slots=True, frozen=True)
class Audio:
    """Áudio mono de 16 bits pronto para tocar."""

    pcm: bytes
    sample_rate: int

    @property
    def seconds(self) -> float:
        return len(self.pcm) / 2 / self.sample_rate if self.sample_rate else 0.0

    def to_wav(self) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(self.sample_rate)
            out.writeframes(self.pcm)
        return buffer.getvalue()


def clean_for_speech(text: str) -> str:
    """Tira marcação, links e emojis que o motor leria em voz alta."""
    text = re.sub(r"https?://\S+", " ", text or "")
    text = re.sub(r"[`*_#>~|]+", " ", text)
    text = re.sub(r"[\U0001F000-\U0001FAFF☀-➿]", " ", text)
    text = re.sub(r"\s*\n+\s*", ". ", text)
    return re.sub(r"\s+", " ", text).strip(" .") + "." if text.strip(" .") else ""


def find_piper_exe() -> Path | None:
    configured = os.getenv("DUQUE_PIPER_EXE")
    candidates = [Path(configured)] if configured else []
    candidates += [PIPER_DIR / "piper.exe", PIPER_DIR / "piper" / "piper.exe", PIPER_DIR / "piper"]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    found = shutil.which("piper")
    return Path(found) if found else None


def find_piper_voice() -> Path | None:
    """Voz escolhida (DUQUE_PIPER_VOICE) ou a primeira .onnx em duque_data/vozes."""
    choice = os.getenv("DUQUE_PIPER_VOICE", "").strip()
    if choice:
        direct = Path(choice)
        for candidate in (direct, VOICES_DIR / choice, VOICES_DIR / f"{choice}.onnx"):
            if candidate.is_file():
                return candidate
        return None
    voices = sorted(VOICES_DIR.glob("*.onnx")) if VOICES_DIR.is_dir() else []
    return voices[0] if voices else None


def list_voices() -> list[str]:
    return [path.stem for path in sorted(VOICES_DIR.glob("*.onnx"))] if VOICES_DIR.is_dir() else []


class PiperEngine:
    name = "piper"

    def __init__(self, exe: Path, voice: Path, run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> None:
        self.exe, self.voice, self._run = exe, voice, run
        config = Path(str(voice) + ".json")
        try:
            self.sample_rate = int(json.loads(config.read_text(encoding="utf-8"))["audio"]["sample_rate"])
        except Exception:
            self.sample_rate = 22050

    def synthesize(self, text: str) -> Audio:
        result = self._run(
            [str(self.exe), "--model", str(self.voice), "--output_raw"],
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=60,
            creationflags=_NO_WINDOW,
        )
        if result.returncode != 0 or not result.stdout:
            detail = (result.stderr or b"").decode("utf-8", "ignore").strip()[-200:]
            raise RuntimeError(f"Piper falhou (código {result.returncode}): {detail}")
        return Audio(result.stdout, self.sample_rate)


_SAPI_SCRIPT = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$want = $env:DUQUE_SAPI_VOICE
$voices = $s.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object { $_.VoiceInfo }
if ($want) { $pick = $voices | Where-Object { $_.Name -like "*$want*" } | Select-Object -First 1 }
if (-not $pick) { $pick = $voices | Where-Object { $_.Culture.Name -eq 'pt-BR' } | Select-Object -First 1 }
if (-not $pick) { $pick = $voices | Where-Object { $_.Culture.Name -like 'pt*' } | Select-Object -First 1 }
if ($pick) { $s.SelectVoice($pick.Name) }
$s.Rate = [int]$env:DUQUE_TTS_RATE
$s.SetOutputToWaveFile($env:DUQUE_TTS_OUT)
$s.Speak($env:DUQUE_TTS_TEXT)
$s.Dispose()
"""


class SapiEngine:
    name = "sapi"

    def __init__(self, run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> None:
        self._run = run

    def synthesize(self, text: str) -> Audio:
        if os.name != "nt":
            raise RuntimeError("A voz do Windows (SAPI) só existe no Windows")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "fala.wav"
            env = {**os.environ, "DUQUE_TTS_TEXT": text, "DUQUE_TTS_OUT": str(out), "DUQUE_TTS_RATE": os.getenv("DUQUE_TTS_RATE", "1")}
            result = self._run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", _SAPI_SCRIPT],
                env=env,
                capture_output=True,
                timeout=60,
                creationflags=_NO_WINDOW,
            )
            if result.returncode != 0 or not out.is_file():
                detail = (result.stderr or b"").decode("utf-8", "ignore").strip()[-200:]
                raise RuntimeError(f"Voz do Windows falhou: {detail}")
            with wave.open(str(out), "rb") as wav:
                channels, width, rate = wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
                frames = wav.readframes(wav.getnframes())
        if width != 2:
            raise RuntimeError(f"Formato de voz não suportado ({width * 8} bits)")
        if channels == 2:  # mistura em mono
            import array

            stereo = array.array("h")
            stereo.frombytes(frames)
            frames = array.array("h", ((stereo[i] + stereo[i + 1]) // 2 for i in range(0, len(stereo) - 1, 2))).tobytes()
        return Audio(frames, rate)


class Speaker:
    """Escolhe o motor e transforma texto em áudio."""

    def __init__(self, engine: PiperEngine | SapiEngine) -> None:
        self.engine = engine

    @property
    def name(self) -> str:
        detail = f" ({self.engine.voice.stem})" if isinstance(self.engine, PiperEngine) else ""
        return self.engine.name + detail

    def synthesize(self, text: str) -> Audio:
        spoken = clean_for_speech(text)
        if not spoken:
            return Audio(b"", 22050)
        return self.engine.synthesize(spoken)


def load(log: Callable[[str], object] = print) -> Speaker | None:
    mode = os.getenv("DUQUE_TTS", "auto").strip().casefold()
    if mode in {"auto", "piper"}:
        exe, voice = find_piper_exe(), find_piper_voice()
        if exe and voice:
            log(f"[TTS] voz local: Piper ({voice.stem}).")
            return Speaker(PiperEngine(exe, voice))
        if mode == "piper":
            log("[TTS] Piper pedido, mas falta o executável ou a voz; rode o preparar_local.bat.")
            return None
    if mode in {"auto", "sapi"} and os.name == "nt":
        log("[TTS] voz local: Windows (SAPI). Para uma voz melhor, instale o Piper (preparar_local.bat).")
        return Speaker(SapiEngine())
    return None


PIPER_URL = os.getenv(
    "DUQUE_PIPER_URL",
    "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip",
)
VOICE_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR"
# Vozes pt-BR do projeto Piper (nome → pasta/qualidade). Todas masculinas, exceto indicado.
KNOWN_VOICES = {
    "faber": "faber/medium/pt_BR-faber-medium",
    "edresson": "edresson/low/pt_BR-edresson-low",
    "cadu": "cadu/medium/pt_BR-cadu-medium",
    "jeff": "jeff/medium/pt_BR-jeff-medium",
}


def _fetch(url: str, target: Path) -> None:
    import urllib.request

    target.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as response, target.open("wb") as out:
        shutil.copyfileobj(response, out)


def download(voice: str = "faber") -> None:
    """Baixa o Piper (~20 MB) e uma voz pt-BR (~60 MB). Roda só quando o Du pede."""
    import zipfile

    if find_piper_exe() is None:
        print(f"Baixando o Piper...\n  {PIPER_URL}")
        PIPER_DIR.mkdir(parents=True, exist_ok=True)
        archive = PIPER_DIR / "piper.zip"
        _fetch(PIPER_URL, archive)
        with zipfile.ZipFile(archive) as zipped:
            zipped.extractall(PIPER_DIR)
        archive.unlink(missing_ok=True)
        print(f"Piper instalado em {PIPER_DIR}")
    path = KNOWN_VOICES.get(voice)
    if path is None:
        raise SystemExit(f"Voz desconhecida: {voice}. Opções: {', '.join(KNOWN_VOICES)}")
    name = path.rsplit("/", 1)[-1]
    if not (VOICES_DIR / f"{name}.onnx").is_file():
        print(f"Baixando a voz {name}...")
        for suffix in (".onnx", ".onnx.json"):
            _fetch(f"{VOICE_BASE}/{path}{suffix}", VOICES_DIR / f"{name}{suffix}")
    print(f"Voz pronta: {name}. Vozes instaladas: {list_voices()}")


if __name__ == "__main__":
    import sys

    if "--baixar" in sys.argv:
        rest = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
        try:
            download(rest[0] if rest else "faber")
        except Exception as exc:
            print(f"[AVISO] Não consegui baixar a voz: {exc}")
    elif "--testar" in sys.argv:
        speaker = load()
        if speaker is None:
            raise SystemExit("Nenhuma voz local disponível.")
        import sounddevice as sd
        import numpy as np

        audio = speaker.synthesize("Olá, Du. Esta é a minha voz. Às suas ordens.")
        sd.play(np.frombuffer(audio.pcm, dtype=np.int16), audio.sample_rate)
        sd.wait()
    else:
        print(__doc__)
