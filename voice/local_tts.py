"""Voz do TELEX no próprio PC, sem API.

Dois motores, escolhidos por DUQUE_TTS (auto | piper | sapi):

- **Piper** (neural, soa natural, funciona offline). É a voz "sua": qualquer
  arquivo ``.onnx`` de voz do Piper colocado em ``duque_data/vozes/`` vira uma
  voz do TELEX. Para trocar de voz, troque o arquivo (ou DUQUE_PIPER_VOICE).
- **SAPI** (as vozes do Windows, como "Microsoft Maria"). Não instala nada;
  serve de reserva quando o Piper ainda não foi instalado.

- **Fish Audio** (opcional, nuvem): só entra se FISH_API_KEY existir. Usa a faixa
  gratuita (``s2.1-pro-free``) e, se o Fish recusar (sem chave válida, sem saldo,
  sem rede), o TELEX cancela e segue com a voz local sem travar.

Em ``auto``: Fish (se houver chave) → Piper (se houver executável e voz) → SAPI.
Variáveis: DUQUE_PIPER_EXE, DUQUE_PIPER_VOICE (caminho ou nome do arquivo),
DUQUE_SAPI_VOICE (parte do nome, ex. "Maria"), DUQUE_TTS_RATE (-10..10, SAPI),
FISH_API_KEY, FISH_VOICE_ID (reference_id da voz), FISH_MODEL (padrão s2.1-pro-free).
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
from typing import Any, Callable

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


# Estilos de voz. "firme": grave, calma e imponente (fala mais devagar, com pausas
# marcadas e o timbre um pouco mais baixo). Ajuste fino: DUQUE_VOICE_PITCH (semitons,
# negativo = mais grave) e DUQUE_VOICE_SPEED (1.0 normal; 0.9 = mais devagar).
STYLES: dict[str, dict[str, float]] = {
    "padrao": {"length_scale": 1.0, "noise_scale": 0.667, "noise_w": 0.8, "sentence_silence": 0.2, "pitch": 0.0, "bass_db": 0.0, "comp": 0.0},
    "firme": {"length_scale": 1.12, "noise_scale": 0.5, "noise_w": 0.6, "sentence_silence": 0.4, "pitch": -2.0, "bass_db": 5.0, "comp": 1.0},
    "grave": {"length_scale": 1.18, "noise_scale": 0.45, "noise_w": 0.55, "sentence_silence": 0.5, "pitch": -3.5, "bass_db": 6.0, "comp": 1.0},
}


def current_style() -> dict[str, float]:
    style = dict(STYLES.get(os.getenv("DUQUE_VOICE_STYLE", "firme").strip().casefold(), STYLES["firme"]))
    try:
        if os.getenv("DUQUE_VOICE_PITCH"):
            style["pitch"] = float(os.environ["DUQUE_VOICE_PITCH"])
        if os.getenv("DUQUE_VOICE_SPEED"):
            style["length_scale"] = 1.0 / max(0.5, float(os.environ["DUQUE_VOICE_SPEED"]))
    except ValueError:
        pass
    return style


# Palavras que os motores leem errado. O Du pode somar as dele em duque_data/pronuncia.txt
# (uma por linha, "palavra=como falar").
PRONUNCIA = {"telex": "télex", "tele x": "télex", "etc.": "etcétera", "km/h": "quilômetros por hora", "%": " por cento", "&": " e ", "wi-fi": "uaifai", "whatsapp": "uatsápi", "youtube": "iutiúbi", "spotify": "espotifai"}


def _pronunciation() -> dict[str, str]:
    table = dict(PRONUNCIA)
    path = ROOT / "duque_data" / "pronuncia.txt"
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                word, said = line.split("=", 1)
                if word.strip():
                    table[word.strip().casefold()] = said.strip()
    except OSError:
        pass
    return table


def fix_pronunciation(text: str) -> str:
    for word, said in _pronunciation().items():
        text = re.sub(rf"(?<!\w){re.escape(word)}(?!\w)" if word[-1].isalnum() else re.escape(word), said, text, flags=re.IGNORECASE)
    return text


def apply_style(audio: "Audio", style: dict[str, float]) -> "Audio":
    """Timbre mais grave e encorpado (pedalboard). Sem o pacote, devolve o áudio como veio."""
    if not audio.pcm or (not style.get("pitch") and not style.get("bass_db")):
        return audio
    try:
        import numpy as np
        from pedalboard import Compressor, Gain, HighpassFilter, LowShelfFilter, Pedalboard, PitchShift  # type: ignore[attr-defined]

        effects: list[Any] = []
        if style.get("pitch"):
            effects.append(PitchShift(semitones=style["pitch"]))
        effects.append(HighpassFilter(cutoff_frequency_hz=70.0))
        if style.get("bass_db"):
            effects.append(LowShelfFilter(cutoff_frequency_hz=200.0, gain_db=style["bass_db"]))
        if style.get("comp"):
            effects.append(Compressor(threshold_db=-22.0, ratio=3.0, attack_ms=8.0, release_ms=150.0))
        effects.append(Gain(gain_db=-2.0))
        samples = np.frombuffer(audio.pcm, dtype=np.int16).astype(np.float32) / 32768.0
        out = Pedalboard(effects)(samples.reshape(1, -1), audio.sample_rate)
        pcm = (np.clip(out.reshape(-1), -1.0, 1.0) * 32767).astype(np.int16).tobytes()
        return Audio(pcm, audio.sample_rate)
    except Exception:
        return audio


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

    @staticmethod
    def _style_args() -> list[str]:
        style = current_style()
        return [
            "--length_scale", f"{style['length_scale']:.2f}",
            "--noise_scale", f"{style['noise_scale']:.2f}",
            "--noise_w", f"{style['noise_w']:.2f}",
            "--sentence_silence", f"{style['sentence_silence']:.2f}",
        ]

    def synthesize(self, text: str) -> Audio:
        result = self._run(
            [str(self.exe), "--model", str(self.voice), "--output_raw", *self._style_args()],
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


def parse_wav(data: bytes) -> Audio:
    """WAV (inclusive de resposta em streaming, com tamanho zerado) → Audio mono de 16 bits."""
    if data[:4] != b"RIFF" or b"fmt " not in data[:200]:
        raise RuntimeError("o Fish não devolveu um WAV")
    fmt = data.index(b"fmt ") + 8
    channels = int.from_bytes(data[fmt + 2 : fmt + 4], "little")
    rate = int.from_bytes(data[fmt + 4 : fmt + 8], "little")
    bits = int.from_bytes(data[fmt + 14 : fmt + 16], "little")
    start = data.index(b"data", fmt) + 8
    pcm = data[start:]
    if bits != 16:
        raise RuntimeError(f"formato de áudio não suportado ({bits} bits)")
    pcm = pcm[: len(pcm) - len(pcm) % (2 * max(1, channels))]
    if channels == 2:
        import array

        stereo = array.array("h")
        stereo.frombytes(pcm)
        pcm = array.array("h", ((stereo[i] + stereo[i + 1]) // 2 for i in range(0, len(stereo) - 1, 2))).tobytes()
    return Audio(pcm, rate)


class FishEngine:
    """Voz do Fish Audio pela API. Qualquer recusa vira erro; quem chama cai para a voz local."""

    name = "fish"
    URL = "https://api.fish.audio/v1/tts"

    def __init__(self, api_key: str, voice_id: str = "", model: str = "", opener: Callable[..., Any] | None = None) -> None:
        import urllib.request

        self.api_key, self.voice_id = api_key, voice_id
        self.model = model or os.getenv("FISH_MODEL", "s2.1-pro-free")
        self._open = opener or urllib.request.urlopen

    def synthesize(self, text: str) -> Audio:
        import urllib.request

        body: dict[str, Any] = {"text": text, "format": "wav", "sample_rate": 24000, "latency": "balanced"}
        if self.voice_id:
            body["reference_id"] = self.voice_id
        request = urllib.request.Request(
            self.URL,
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json", "model": self.model},
        )
        try:
            with self._open(request, timeout=30) as response:
                return parse_wav(response.read())
        except Exception as exc:
            code = getattr(exc, "code", None)
            raise RuntimeError(f"Fish Audio recusou ({code or type(exc).__name__})") from exc


class FallbackEngine:
    """Tenta o motor principal; se falhar, usa o reserva e deixa o principal de castigo por um tempo."""

    def __init__(self, primary: Any, backup: Any, cooldown: float = 300.0, clock: Callable[[], float] | None = None) -> None:
        import time

        self.primary, self.backup, self.cooldown = primary, backup, cooldown
        self._clock = clock or time.monotonic
        self._blocked_until = 0.0
        self.name = primary.name
        self.last_error: str | None = None

    def synthesize(self, text: str) -> Audio:
        if self._clock() >= self._blocked_until:
            try:
                return self.primary.synthesize(text)
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                self._blocked_until = self._clock() + self.cooldown
        return self.backup.synthesize(text)


class Speaker:
    """Escolhe o motor e transforma texto em áudio."""

    def __init__(self, engine: Any) -> None:
        self.engine = engine

    @property
    def name(self) -> str:
        engine = self.engine
        if isinstance(engine, FallbackEngine):
            return f"{engine.name} (reserva: {Speaker(engine.backup).name})"
        return engine.name + (f" ({engine.voice.stem})" if isinstance(engine, PiperEngine) else "")

    def synthesize(self, text: str) -> Audio:
        spoken = fix_pronunciation(clean_for_speech(text))
        if not spoken:
            return Audio(b"", 22050)
        return apply_style(self.engine.synthesize(spoken), current_style())


def _load_local(mode: str, log: Callable[[str], object]) -> Speaker | None:
    if mode in {"auto", "fish", "piper"}:
        exe, voice = find_piper_exe(), find_piper_voice()
        if exe and voice:
            log(f"[TTS] voz local: Piper ({voice.stem}).")
            return Speaker(PiperEngine(exe, voice))
        if mode == "piper":
            log("[TTS] Piper pedido, mas falta o executável ou a voz; rode o preparar_local.bat.")
            return None
    if mode in {"auto", "fish", "sapi"} and os.name == "nt":
        log("[TTS] voz local: Windows (SAPI). Para uma voz melhor, instale o Piper (preparar_local.bat).")
        return Speaker(SapiEngine())
    return None


def load(log: Callable[[str], object] = print) -> Speaker | None:
    mode = os.getenv("DUQUE_TTS", "auto").strip().casefold()
    local = _load_local(mode, log)
    key = os.getenv("FISH_API_KEY", "").strip()
    if mode in {"auto", "fish"} and key:
        # Sem FISH_API_KEY o Fish nunca é chamado: o TELEX fica 100% local.
        fish = FishEngine(key, os.getenv("FISH_VOICE_ID", "").strip())
        log(f"[TTS] voz: Fish Audio ({fish.model})" + (", com a voz local de reserva." if local else ", sem reserva local."))
        return Speaker(FallbackEngine(fish, local.engine)) if local else Speaker(fish)
    if mode == "fish":
        log("[TTS] Fish pedido, mas falta FISH_API_KEY; seguindo com a voz local.")
    return local


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
    elif "--amostras" in sys.argv:
        import numpy as np
        import sounddevice as sd

        speaker = load()
        if speaker is None:
            raise SystemExit("Nenhuma voz local disponível.")
        frase = "Atenção, Du. Missão dada é missão cumprida. Pode contar comigo."
        for nome in STYLES:
            os.environ["DUQUE_VOICE_STYLE"] = nome
            print(f"Estilo: {nome}")
            audio = speaker.synthesize(frase)
            sd.play(np.frombuffer(audio.pcm, dtype=np.int16), audio.sample_rate)
            sd.wait()
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
