from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import urllib.request
from collections import deque
from pathlib import Path

import numpy as np
import openwakeword
import sounddevice as sd
from openwakeword.model import Model
from pvrecorder import PvRecorder
from pedalboard import Pedalboard, Compressor, Gain, HighpassFilter, LowShelfFilter, time_stretch
from agents.realtime import OpenAIRealtimeWebSocketModel, RealtimeRunner, RealtimePlaybackTracker
from agent.duque_realtime import duque_realtime
from voice.session import PlaybackFence

MODEL = os.getenv("DUQUE_REALTIME_MODEL", "gpt-realtime-2.1")
VOICE = os.getenv("DUQUE_VOICE", "cedar")
MICROFONE = int(os.getenv("DUQUE_MIC", "1"))
SAMPLE_RATE = 24000
CANAIS = 1
BLOCKSIZE = 480
SERVIDOR = "http://127.0.0.1:5000"
WAKEWORD = "hey_jarvis"
FRAME_LENGTH = 1280
WAKE_THRESHOLD = float(os.getenv("DUQUE_WAKE_THRESHOLD", "0.5"))
WAKE_COOLDOWN = 2.0
LOCAL_VAD_THRESHOLD = float(os.getenv("DUQUE_VAD_THRESHOLD", "0.045"))
LOCAL_VAD_BLOCKS = 3
LOCAL_VAD_COOLDOWN = 0.8
LOCAL_VAD_IGNORE_AFTER_SPEECH = 0.25
PITCH_SEMITONES = float(os.getenv("DUQUE_PITCH", "-2.0"))
VOICE_SPEED = float(os.getenv("DUQUE_VOICE_SPEED", "0.96"))
# O processamento pesado de pitch/time-stretch fica desligado por padrão.
# O Realtime deve priorizar continuidade do áudio; podemos reintroduzir o
# processamento em uma etapa assíncrona dedicada depois.
VOICE_PROCESSING = os.getenv("DUQUE_VOICE_PROCESSING", "0").casefold() in {"1", "true", "yes", "on"}

FAREWELLS = (
    "até mais duque", "até logo duque", "tchau duque", "pode dormir duque",
    "até mais, duque", "até logo, duque", "tchau, duque", "pode dormir, duque",
)

voice_board = Pedalboard([
    HighpassFilter(cutoff_frequency_hz=60.0),
    LowShelfFilter(cutoff_frequency_hz=180.0, gain_db=3.0),
    Compressor(threshold_db=-24.0, ratio=2.5, attack_ms=10.0, release_ms=120.0),
    Gain(gain_db=-1.0),
])

model = OpenAIRealtimeWebSocketModel(transport_config={
    "ping_interval": 20.0, "ping_timeout": 60.0,
    "handshake_timeout": 30.0, "max_size": 8 * 1024 * 1024,
})
runner = RealtimeRunner(
    starting_agent=duque_realtime,
    model=model,
    config={
        "model_settings": {
            "model_name": MODEL,
            "audio": {
                "input": {
                    "format": "pcm16",
                    "noise_reduction": {"type": "far_field"},
                    "transcription": {"model": "gpt-4o-mini-transcribe", "language": "pt"},
                    "turn_detection": {
                        "type": "server_vad", "threshold": 0.3,
                        "prefix_padding_ms": 300, "silence_duration_ms": 250,
                        "interrupt_response": True, "create_response": True,
                    },
                },
                "output": {"format": "pcm16", "voice": VOICE},
            },
        },
        "tracing_disabled": True,
    },
)

state_lock = threading.Lock()
REALTIME = False
MIC_ACTIVE = False
DUQUE_SPEAKING = False
SHUTTING_DOWN = False
SESSION = None
LOOP = None
MIC_QUEUE: asyncio.Queue[bytes] | None = None
TRACKER: RealtimePlaybackTracker | None = None
FENCE = PlaybackFence()
AUDIO = deque()
AUDIO_LOCK = threading.Lock()
PROCESSING = bytearray()
PROCESSING_LOCK = threading.Lock()
CURRENT_ITEM: str | None = None
CANCELLED: set[str] = set()
CANCELLED_LOCK = threading.Lock()
PLAYBACK_DRAINED = threading.Event()
PLAYBACK_DRAINED.set()
SHUTDOWN_EVENT: asyncio.Event | None = None
VAD_COUNT = 0
LAST_INTERRUPT = 0.0
SPEECH_STARTED_AT: float | None = None


def hud(state: str, task: str = "") -> None:
    try:
        body = json.dumps({"estado": state, "tarefa": task}).encode()
        request = urllib.request.Request(
            f"{SERVIDOR}/api/estado", data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=0.5):
            pass
    except Exception:
        pass


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def is_farewell(text: str) -> bool:
    normalized = " ".join((text or "").casefold().split())
    return any(phrase in normalized for phrase in FAREWELLS)


def rms(data: bytes) -> float:
    try:
        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        return float(np.sqrt(np.mean(samples * samples))) if len(samples) else 0.0
    except Exception:
        return 0.0


def cancelled(item_id: str | None) -> bool:
    with CANCELLED_LOCK:
        return item_id is not None and item_id in CANCELLED


def clear_audio() -> None:
    with AUDIO_LOCK:
        AUDIO.clear()
    with PROCESSING_LOCK:
        PROCESSING.clear()
    PLAYBACK_DRAINED.set()


def reset_voice_processor() -> None:
    try:
        voice_board.reset()
    except Exception:
        pass


def process_audio(data: bytes) -> bytes:
    if not VOICE_PROCESSING:
        return data
    try:
        audio = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        audio = voice_board.process(audio.reshape(1, -1), SAMPLE_RATE, buffer_size=2048, reset=False)
        audio = time_stretch(
            audio, SAMPLE_RATE, stretch_factor=VOICE_SPEED,
            pitch_shift_in_semitones=PITCH_SEMITONES,
            high_quality=True, transient_mode="crisp",
            transient_detector="compound", retain_phase_continuity=True,
            preserve_formants=True,
        )
        return (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
    except Exception as exc:
        log(f"[VOZ] processamento falhou; usando áudio original: {exc}")
        return data


def enqueue_audio(data: bytes, item_id: str, content_index: int) -> None:
    global CURRENT_ITEM
    if cancelled(item_id) or FENCE.stale(FENCE.state.generation):
        return
    processed = process_audio(data)
    with AUDIO_LOCK:
        AUDIO.append((item_id, content_index, processed))
        PLAYBACK_DRAINED.clear()
    with state_lock:
        CURRENT_ITEM = item_id


def output_callback(outdata, frames, _time_info, status) -> None:
    if status:
        log(f"[PLAYER] {status}")
    needed = frames * 2 * CANAIS
    result = bytearray()
    played: list[tuple[str, int, bytes]] = []
    with AUDIO_LOCK:
        while len(result) < needed and AUDIO:
            item_id, content_index, data = AUDIO[0]
            if cancelled(item_id):
                AUDIO.popleft()
                continue
            remaining = needed - len(result)
            chunk, rest = data[:remaining], data[remaining:]
            result.extend(chunk)
            if rest:
                AUDIO[0] = (item_id, content_index, rest)
            else:
                AUDIO.popleft()
            played.append((item_id, content_index, chunk))
        if not AUDIO:
            with PROCESSING_LOCK:
                processing_empty = not PROCESSING
            if processing_empty:
                PLAYBACK_DRAINED.set()
    if len(result) < needed:
        result.extend(b"\x00" * (needed - len(result)))
    outdata[:] = bytes(result)
    if TRACKER:
        for item_id, content_index, chunk in played:
            try:
                TRACKER.on_play_bytes(item_id, content_index, chunk)
            except Exception:
                pass


def microphone_callback(indata, _frames, _time_info, status) -> None:
    global VAD_COUNT, LAST_INTERRUPT
    if status:
        log(f"[MIC] {status}")
    if not REALTIME or not MIC_ACTIVE or LOOP is None or MIC_QUEUE is None:
        return
    audio = indata.copy().tobytes()
    if DUQUE_SPEAKING and not SHUTTING_DOWN:
        now = time.perf_counter()
        if SPEECH_STARTED_AT is None or now - SPEECH_STARTED_AT >= LOCAL_VAD_IGNORE_AFTER_SPEECH:
            VAD_COUNT = VAD_COUNT + 1 if rms(audio) >= LOCAL_VAD_THRESHOLD else 0
            if VAD_COUNT >= LOCAL_VAD_BLOCKS and now - LAST_INTERRUPT >= LOCAL_VAD_COOLDOWN:
                VAD_COUNT = 0
                LAST_INTERRUPT = now
                LOOP.call_soon_threadsafe(lambda: asyncio.create_task(interrupt_session()))
    try:
        LOOP.call_soon_threadsafe(MIC_QUEUE.put_nowait, audio)
    except Exception:
        pass


async def interrupt_session() -> None:
    if SESSION is None or SHUTTING_DOWN:
        return
    clear_audio()
    reset_voice_processor()
    try:
        await SESSION.interrupt()
    except Exception as exc:
        log(f"[VAD] interrupção falhou: {exc}")


def request_shutdown() -> None:
    global SHUTTING_DOWN, MIC_ACTIVE
    if SHUTTING_DOWN:
        return
    SHUTTING_DOWN = True
    MIC_ACTIVE = False
    if MIC_QUEUE:
        while not MIC_QUEUE.empty():
            try:
                MIC_QUEUE.get_nowait()
            except asyncio.QueueEmpty:
                break
    FENCE.shutdown()
    hud("processando", "Encerrando conversa...")
    log("Encerramento solicitado; microfone desativado.")


async def send_microphone(session) -> None:
    while REALTIME:
        try:
            audio = await asyncio.wait_for(MIC_QUEUE.get(), timeout=0.1)
        except asyncio.TimeoutError:
            continue
        if MIC_ACTIVE and REALTIME and not SHUTTING_DOWN:
            try:
                await session.send_audio(audio)
            except Exception as exc:
                log(f"[MIC] envio falhou: {exc}")
                return


async def wait_playback() -> None:
    await asyncio.to_thread(PLAYBACK_DRAINED.wait)
    await asyncio.sleep(0.15)


def extract_text(value, depth: int = 0) -> str:
    if value is None or depth > 6:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(filter(None, (extract_text(v, depth + 1) for v in value.values())))
    if isinstance(value, (list, tuple, set)):
        return " ".join(filter(None, (extract_text(v, depth + 1) for v in value)))
    parts = []
    for name in ("text", "transcript", "transcription", "delta", "item", "content", "parts", "data"):
        try:
            value2 = getattr(value, name, None)
        except Exception:
            value2 = None
        if value2 is not None:
            parts.append(extract_text(value2, depth + 1))
    return " ".join(filter(None, parts))


def extract_raw_text(data, raw_type: str) -> str:
    """Extrai apenas eventos que realmente carregam texto.

    Nunca trata response.output_audio.delta como texto: o SDK já converte
    esse delta em evento `audio`; o campo bruto é Base64 de áudio.
    """
    text_types = {
        "conversation.item.input_audio_transcription.completed",
        "response.output_audio_transcript.delta",
        "response.output_text.delta",
    }
    if raw_type not in text_types:
        return ""
    return extract_text(data).strip()


async def receive_events(session) -> None:
    global DUQUE_SPEAKING, SPEECH_STARTED_AT, CURRENT_ITEM
    async for event in session:
        if not REALTIME:
            return
        kind = getattr(event, "type", "")
        if kind == "raw_model_event":
            data = getattr(event, "data", None)
            raw_type = getattr(data, "type", "")
            if raw_type == "input_audio_buffer.speech_started" and not SHUTTING_DOWN:
                hud("ouvindo", "Escutando você...")
            text = extract_raw_text(data, raw_type)
            if text and is_farewell(text):
                request_shutdown()
        elif kind == "audio":
            item_id = event.audio.item_id
            if cancelled(item_id) or SHUTTING_DOWN:
                continue
            if not DUQUE_SPEAKING:
                DUQUE_SPEAKING = True
                SPEECH_STARTED_AT = time.perf_counter()
                hud("falando", "Duque falando...")
            FENCE.can_enqueue(FENCE.state.generation, item_id)
            enqueue_audio(event.audio.data, item_id, event.audio.content_index)
        elif kind == "audio_interrupted":
            item_id = CURRENT_ITEM
            if item_id:
                with CANCELLED_LOCK:
                    CANCELLED.add(item_id)
            clear_audio()
            reset_voice_processor()
            DUQUE_SPEAKING = False
            SPEECH_STARTED_AT = None
            if TRACKER:
                try:
                    TRACKER.on_interrupted()
                except Exception:
                    pass
            if not SHUTTING_DOWN:
                hud("ouvindo", "Escutando você...")
        elif kind == "agent_start":
            DUQUE_SPEAKING = False
            SPEECH_STARTED_AT = None
            if not SHUTTING_DOWN:
                hud("processando", "Processando comando...")
        elif kind == "agent_end":
            if SHUTTING_DOWN:
                await wait_playback()
                if SHUTDOWN_EVENT:
                    SHUTDOWN_EVENT.set()
                return
            await wait_playback()
            DUQUE_SPEAKING = False
            SPEECH_STARTED_AT = None
            hud("ouvindo", "Escutando você...")
        elif kind == "error":
            log(f"[REALTIME] erro: {getattr(event, 'error', event)}")
            return


async def realtime_session() -> None:
    global LOOP, MIC_QUEUE, SHUTDOWN_EVENT, REALTIME, MIC_ACTIVE, SESSION, TRACKER
    global DUQUE_SPEAKING, SHUTTING_DOWN, SPEECH_STARTED_AT, CURRENT_ITEM
    LOOP = asyncio.get_running_loop()
    MIC_QUEUE = asyncio.Queue(maxsize=100)
    SHUTDOWN_EVENT = asyncio.Event()
    FENCE.new_session()
    REALTIME = True
    MIC_ACTIVE = False
    SHUTTING_DOWN = False
    DUQUE_SPEAKING = False
    CURRENT_ITEM = None
    with CANCELLED_LOCK:
        CANCELLED.clear()
    clear_audio()
    reset_voice_processor()
    hud("ouvindo", "Escutando você...")
    player = None
    input_stream = None
    try:
        player = sd.RawOutputStream(samplerate=SAMPLE_RATE, channels=CANAIS, dtype="int16", blocksize=BLOCKSIZE, callback=output_callback)
        player.start()
        TRACKER = RealtimePlaybackTracker()
        session = await runner.run(model_config={"playback_tracker": TRACKER})
        async with session:
            SESSION = session
            input_stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=CANAIS, dtype=np.int16, device=MICROFONE, blocksize=BLOCKSIZE, callback=microphone_callback)
            input_stream.start()
            MIC_ACTIVE = True
            mic_task = asyncio.create_task(send_microphone(session))
            event_task = asyncio.create_task(receive_events(session))
            shutdown_task = asyncio.create_task(SHUTDOWN_EVENT.wait())
            done, pending = await asyncio.wait((mic_task, event_task, shutdown_task), return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                try:
                    task.result()
                except Exception as exc:
                    log(f"[REALTIME] tarefa terminou com erro: {exc}")
    except Exception as exc:
        log(f"[REALTIME] sessão falhou: {exc!r}")
    finally:
        MIC_ACTIVE = False
        if input_stream:
            try:
                input_stream.stop()
                input_stream.close()
            except Exception:
                pass
        await wait_playback()
        if player:
            try:
                player.stop()
                player.close()
            except Exception:
                pass
        REALTIME = False
        SESSION = None
        FENCE.close()
        clear_audio()
        with CANCELLED_LOCK:
            CANCELLED.clear()
        TRACKER = None
        MIC_QUEUE = None
        SHUTDOWN_EVENT = None
        LOOP = None
        DUQUE_SPEAKING = False
        SPEECH_STARTED_AT = None
        CURRENT_ITEM = None
        hud("standby", "Sistema online")


def wake_loop() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY não encontrada")

    wake_model_path = Path(openwakeword.__file__).resolve().parent / "resources" / "models" / "hey_jarvis_v0.1.onnx"
    if not wake_model_path.exists():
        raise SystemExit(f"Modelo wake word não encontrado: {wake_model_path}")

    wake_model = Model(
        wakeword_models=[str(wake_model_path)],
        inference_framework="onnx",
    )
    recorder = None
    last_wake = 0.0
    hud("standby", "Sistema online")
    try:
        recorder = PvRecorder(frame_length=FRAME_LENGTH, device_index=0)
        recorder.start()
        log('Wake word ativo: "Hey Jarvis"')
        while True:
            frame = np.asarray(recorder.read(), dtype=np.int16)
            confidence = wake_model.predict(frame).get(WAKEWORD, 0.0)
            now = time.perf_counter()
            if confidence >= WAKE_THRESHOLD and now - last_wake >= WAKE_COOLDOWN:
                last_wake = now
                recorder.stop()
                recorder.delete()
                recorder = None
                asyncio.run(realtime_session())
                recorder = PvRecorder(frame_length=FRAME_LENGTH, device_index=0)
                recorder.start()
    except KeyboardInterrupt:
        pass
    finally:
        if recorder:
            try:
                recorder.stop()
                recorder.delete()
            except Exception:
                pass
        hud("standby", "Sistema offline")


if __name__ == "__main__":
    log(f"Duque Realtime {MODEL} | voz={VOICE} | processamento={'on' if VOICE_PROCESSING else 'off'}")
    wake_loop()
