from __future__ import annotations

import asyncio
import json
import os
import queue
import threading
import time
import urllib.request
from collections import deque
from pathlib import Path
from typing import Any, Coroutine, cast

import numpy as np
import openwakeword
import sounddevice as sd
from openwakeword.model import Model
from pvrecorder import PvRecorder
from pedalboard import Compressor, Gain, HighpassFilter, LowShelfFilter, Pedalboard, time_stretch  # pyright: ignore[reportPrivateImportUsage]
from agents.realtime import OpenAIRealtimeWebSocketModel, RealtimeRunner, RealtimePlaybackTracker
from agent.duque_realtime import duque_realtime
from voice.session import PlaybackFence, error_details, is_benign_error, is_farewell, is_fatal_error


def _env_flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().casefold() in {"1", "true", "yes", "on", "sim"}


def _env_int(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    return int(value) if value else None


MODEL = os.getenv("DUQUE_REALTIME_MODEL", "gpt-realtime-2.1")
VOICE = os.getenv("DUQUE_VOICE", "cedar")
# Microfone da conversa (índice do sounddevice). Sem DUQUE_MIC, usa o mesmo
# dispositivo do wake word (procurado pelo nome) ou o padrão do sistema.
MIC_OVERRIDE = _env_int("DUQUE_MIC")
MICROFONE: int | None = MIC_OVERRIDE
# Microfone do wake word (índice do PvRecorder; -1 = padrão do sistema).
WAKE_MIC_OVERRIDE = _env_int("DUQUE_WAKE_MIC")
WAKE_MICROFONE = WAKE_MIC_OVERRIDE if WAKE_MIC_OVERRIDE is not None else 1
SAMPLE_RATE = 24000
CANAIS = 1
BLOCKSIZE = 480
SERVIDOR = "http://127.0.0.1:5000"
WAKEWORD = "hey_jarvis"
WAKEWORD_MODEL_NAME = "hey_jarvis_v0.1"
FRAME_LENGTH = 1280
WAKE_THRESHOLD = float(os.getenv("DUQUE_WAKE_THRESHOLD", "0.5"))
WAKE_COOLDOWN = 2.0
# O VAD local interrompe o Duque quando o microfone capta som alto enquanto ele
# fala. Sem cancelamento de eco (caixas de som), ele capta a própria voz do
# Duque e se interrompe sozinho; por isso é opcional e o VAD do servidor manda.
LOCAL_VAD = _env_flag("DUQUE_LOCAL_VAD")
LOCAL_VAD_THRESHOLD = float(os.getenv("DUQUE_VAD_THRESHOLD", "0.045"))
LOCAL_VAD_BLOCKS = 3
LOCAL_VAD_COOLDOWN = 0.8
LOCAL_VAD_IGNORE_AFTER_SPEECH = 0.25
PITCH_SEMITONES = float(os.getenv("DUQUE_PITCH", "-2.0"))
VOICE_SPEED = float(os.getenv("DUQUE_VOICE_SPEED", "0.96"))
VOICE_PROCESSING = _env_flag("DUQUE_VOICE_PROCESSING")
# Sem fala do usuário (e sem o Duque falando) por este tempo, a sessão encerra.
IDLE_SECONDS = float(os.getenv("DUQUE_VOICE_IDLE_SECONDS", "60"))
PLAYBACK_TIMEOUT = 15.0
FAREWELL_TIMEOUT = 8.0

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
LOOP: asyncio.AbstractEventLoop | None = None
MIC_QUEUE: asyncio.Queue[bytes] | None = None
TRACKER: RealtimePlaybackTracker | None = None
FENCE = PlaybackFence()
# Cada item: (item_id, content_index, áudio a tocar, razão bytes originais/tocados).
AUDIO: deque[tuple[str, int, bytes, float]] = deque()
AUDIO_LOCK = threading.Lock()
CURRENT_ITEM: str | None = None
CANCELLED: set[str] = set()
CANCELLED_LOCK = threading.Lock()
PLAYBACK_DRAINED = threading.Event()
PLAYBACK_DRAINED.set()
SHUTDOWN_EVENT: asyncio.Event | None = None
VAD_COUNT = 0
LAST_INTERRUPT = 0.0
SPEECH_STARTED_AT: float | None = None
LAST_ACTIVITY = 0.0
# Incrementado a cada resposta: tarefas atrasadas de uma resposta antiga não
# mexem no estado da resposta seguinte.
RESPONSE_SEQ = 0
BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()

# Envio de estado ao HUD fora do event loop: uma única thread, em ordem.
HUD_QUEUE: queue.Queue[tuple[str, str, str]] = queue.Queue(maxsize=64)
HUD_THREAD: threading.Thread | None = None
HUD_THREAD_LOCK = threading.Lock()


def _post_hud(state: str, task: str, mode: str) -> None:
    body = json.dumps({"estado": state, "tarefa": task, "modo": mode}).encode()
    request = urllib.request.Request(
        f"{SERVIDOR}/api/estado", data=body,
        headers={
            "Content-Type": "application/json",
            "X-Duque-Token": os.getenv("DUQUE_API_TOKEN", ""),
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=1.0):
        pass


def _hud_worker() -> None:
    while True:
        state, task, mode = HUD_QUEUE.get()
        try:
            _post_hud(state, task, mode)
        except Exception:
            pass


def hud(state: str, task: str = "", mode: str = "voz") -> None:
    """Publica o estado no HUD sem bloquear quem chama (inclusive o event loop).

    ``mode`` é "voz" durante a conversa e "texto" fora dela.
    """
    global HUD_THREAD
    with HUD_THREAD_LOCK:
        if HUD_THREAD is None or not HUD_THREAD.is_alive():
            HUD_THREAD = threading.Thread(target=_hud_worker, name="duque-hud", daemon=True)
            HUD_THREAD.start()
    try:
        HUD_QUEUE.put_nowait((state, task, mode))
    except queue.Full:
        pass  # servidor fora do ar; estados antigos não importam


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def touch() -> None:
    """Marca atividade da conversa (para o encerramento por inatividade)."""
    global LAST_ACTIVITY
    LAST_ACTIVITY = time.monotonic()


def spawn(coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
    """Cria uma tarefa mantendo referência até ela terminar (evita coleta precoce)."""
    task = asyncio.create_task(coro)
    BACKGROUND_TASKS.add(task)
    task.add_done_callback(BACKGROUND_TASKS.discard)
    return task


def run_in_loop(factory) -> None:
    """Agenda ``factory()`` (que cria uma corrotina) no loop da sessão, de outra thread."""
    loop = LOOP
    if loop is None:
        return
    try:
        loop.call_soon_threadsafe(lambda: spawn(factory()))
    except RuntimeError:
        pass  # loop já encerrado


def rms(data: bytes) -> float:
    try:
        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        return float(np.sqrt(np.mean(samples * samples))) if len(samples) else 0.0
    except Exception:
        return 0.0


def cancelled(item_id: str | None) -> bool:
    with CANCELLED_LOCK:
        return item_id is not None and item_id in CANCELLED


def cancel_current_item() -> None:
    """Descarta o restante da resposta atual (deltas em trânsito inclusive)."""
    item_id = CURRENT_ITEM
    if item_id:
        with CANCELLED_LOCK:
            CANCELLED.add(item_id)


def clear_audio() -> None:
    with AUDIO_LOCK:
        AUDIO.clear()
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


def enqueue_audio(data: bytes, item_id: str, content_index: int, generation: int) -> None:
    global CURRENT_ITEM
    if cancelled(item_id) or not FENCE.accepts(generation):
        return
    processed = process_audio(data)
    # O tracker do SDK precisa saber quanto do áudio ORIGINAL já tocou (para
    # truncar a resposta certa numa interrupção), mesmo com time-stretch.
    ratio = len(data) / len(processed) if processed else 1.0
    with AUDIO_LOCK:
        AUDIO.append((item_id, content_index, processed, ratio))
        PLAYBACK_DRAINED.clear()
    with state_lock:
        CURRENT_ITEM = item_id


def report_playback(item_id: str, content_index: int, chunk: bytes, ratio: float) -> None:
    tracker = TRACKER
    if tracker is None or not chunk:
        return
    try:
        if ratio == 1.0:
            tracker.on_play_bytes(item_id, content_index, chunk)
        else:
            original_ms = len(chunk) / 2 / CANAIS / SAMPLE_RATE * 1000.0 * ratio
            tracker.on_play_ms(item_id, content_index, original_ms)
    except Exception:
        pass


def output_callback(outdata, frames, _time_info, status) -> None:
    if status:
        log(f"[PLAYER] {status}")
    needed = frames * 2 * CANAIS
    result = bytearray()
    played: list[tuple[str, int, bytes, float]] = []
    with AUDIO_LOCK:
        while len(result) < needed and AUDIO:
            item_id, content_index, data, ratio = AUDIO[0]
            if cancelled(item_id):
                AUDIO.popleft()
                continue
            remaining = needed - len(result)
            chunk, rest = data[:remaining], data[remaining:]
            result.extend(chunk)
            if rest:
                AUDIO[0] = (item_id, content_index, rest, ratio)
            else:
                AUDIO.popleft()
            played.append((item_id, content_index, chunk, ratio))
        if not AUDIO:
            PLAYBACK_DRAINED.set()
    if len(result) < needed:
        result.extend(b"\x00" * (needed - len(result)))
    outdata[:] = bytes(result)
    for item_id, content_index, chunk, ratio in played:
        report_playback(item_id, content_index, chunk, ratio)


def microphone_callback(indata, _frames, _time_info, status) -> None:
    global VAD_COUNT, LAST_INTERRUPT
    if status:
        log(f"[MIC] {status}")
    loop = LOOP
    if not REALTIME or not MIC_ACTIVE or loop is None or MIC_QUEUE is None:
        return
    audio = indata.copy().tobytes()
    if LOCAL_VAD and DUQUE_SPEAKING and not SHUTTING_DOWN:
        now = time.perf_counter()
        if SPEECH_STARTED_AT is None or now - SPEECH_STARTED_AT >= LOCAL_VAD_IGNORE_AFTER_SPEECH:
            VAD_COUNT = VAD_COUNT + 1 if rms(audio) >= LOCAL_VAD_THRESHOLD else 0
            if VAD_COUNT >= LOCAL_VAD_BLOCKS and now - LAST_INTERRUPT >= LOCAL_VAD_COOLDOWN:
                VAD_COUNT = 0
                LAST_INTERRUPT = now
                run_in_loop(interrupt_session)

    def enqueue() -> None:
        queue_ = MIC_QUEUE
        if queue_ is None or not REALTIME or not MIC_ACTIVE or SHUTTING_DOWN:
            return
        try:
            queue_.put_nowait(audio)
        except asyncio.QueueFull:
            # Durante uma falha do transporte, o frame atual é descartável.
            pass

    try:
        loop.call_soon_threadsafe(enqueue)
    except RuntimeError:
        pass


async def interrupt_session() -> None:
    if SESSION is None or SHUTTING_DOWN:
        return
    cancel_current_item()
    clear_audio()
    reset_voice_processor()
    try:
        await SESSION.interrupt()
    except Exception as exc:
        log(f"[VAD] interrupção falhou: {exc}")


async def finish_shutdown() -> None:
    """Rede de segurança: se a despedida não terminar (agent_end), encerra mesmo assim."""
    event = SHUTDOWN_EVENT
    if event is None:
        return
    try:
        await asyncio.wait_for(event.wait(), timeout=FAREWELL_TIMEOUT)
    except asyncio.TimeoutError:
        log("[REALTIME] despedida não concluiu a tempo; encerrando a sessão.")
        await wait_playback()
        event.set()


def request_shutdown() -> None:
    """Corta o microfone na hora, mas deixa a resposta de despedida terminar.

    O fim normal vem do agent_end da despedida; ``finish_shutdown`` é o limite.
    """
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
    hud("processando", "Encerrando conversa...")
    log("Encerramento solicitado; microfone desativado. A despedida continua liberada.")
    if SHUTDOWN_EVENT is not None:
        run_in_loop(finish_shutdown)


async def send_microphone(session) -> None:
    queue_ = MIC_QUEUE
    if queue_ is None:
        return
    while REALTIME:
        try:
            audio = await asyncio.wait_for(queue_.get(), timeout=0.1)
        except asyncio.TimeoutError:
            continue
        if MIC_ACTIVE and REALTIME and not SHUTTING_DOWN:
            try:
                await session.send_audio(audio)
            except Exception as exc:
                log(f"[MIC] envio falhou: {exc}")
                return


async def wait_playback(timeout: float = PLAYBACK_TIMEOUT) -> None:
    """Espera o áudio enfileirado tocar, no máximo ``timeout`` segundos."""
    drained = await asyncio.to_thread(PLAYBACK_DRAINED.wait, timeout)
    if not drained:
        log(f"[PLAYER] áudio não terminou em {timeout:.0f}s; descartando o restante.")
        clear_audio()
        return
    await asyncio.sleep(0.15)


async def idle_watchdog() -> None:
    """Encerra a conversa depois de IDLE_SECONDS sem ninguém falar."""
    while REALTIME:
        await asyncio.sleep(1.0)
        if SHUTTING_DOWN or (DUQUE_SPEAKING and not PLAYBACK_DRAINED.is_set()):
            continue
        if time.monotonic() - LAST_ACTIVITY >= IDLE_SECONDS:
            log(f"[REALTIME] {IDLE_SECONDS:.0f}s sem conversa; encerrando a sessão.")
            if SHUTDOWN_EVENT is not None:
                SHUTDOWN_EVENT.set()
            return


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
    text_types = {
        "conversation.item.input_audio_transcription.completed",
        "response.output_audio_transcript.delta",
        "response.output_text.delta",
    }
    if raw_type not in text_types:
        return ""
    return extract_text(data).strip()


async def after_response(sequence: int) -> None:
    """Depois que a resposta terminou de tocar, volta a ouvir (ou encerra)."""
    global DUQUE_SPEAKING, SPEECH_STARTED_AT
    await wait_playback()
    if sequence != RESPONSE_SEQ or not REALTIME:
        return  # outra resposta começou nesse meio-tempo
    DUQUE_SPEAKING = False
    SPEECH_STARTED_AT = None
    touch()
    if SHUTTING_DOWN:
        if SHUTDOWN_EVENT:
            SHUTDOWN_EVENT.set()
        return
    hud("ouvindo", "Escutando você...")


async def receive_events(session) -> None:
    """Consome eventos da sessão sem despejar deltas de áudio Base64 no log."""
    global DUQUE_SPEAKING, SPEECH_STARTED_AT, RESPONSE_SEQ
    DUQUE_SPEAKING = False
    SPEECH_STARTED_AT = None
    generation = FENCE.generation
    async for event in session:
        if not REALTIME:
            return
        kind = getattr(event, "type", "")
        if kind == "raw_model_event":
            data = getattr(event, "data", None)
            raw_type = getattr(data, "type", "")
            if raw_type in {"input_audio_buffer.speech_started", "input_audio_buffer.speech_stopped"}:
                touch()
                if raw_type == "input_audio_buffer.speech_started" and not SHUTTING_DOWN:
                    hud("ouvindo", "Escutando você...")
            text = extract_raw_text(data, raw_type)
            if text and is_farewell(text):
                request_shutdown()
        elif kind == "history_added":
            text = extract_text(getattr(event, "item", event)).strip()
            if text and is_farewell(text):
                request_shutdown()
        elif kind == "audio":
            item_id = event.audio.item_id
            if cancelled(item_id) or not FENCE.accepts(generation):
                continue
            touch()
            if not DUQUE_SPEAKING:
                DUQUE_SPEAKING = True
                SPEECH_STARTED_AT = time.perf_counter()
                hud("falando", "Duque falando...")
            enqueue_audio(event.audio.data, item_id, event.audio.content_index, generation)
        elif kind == "audio_interrupted":
            cancel_current_item()
            clear_audio()
            reset_voice_processor()
            DUQUE_SPEAKING = False
            SPEECH_STARTED_AT = None
            touch()
            if TRACKER:
                try:
                    TRACKER.on_interrupted()
                except Exception:
                    pass
            if not SHUTTING_DOWN:
                hud("ouvindo", "Escutando você...")
        elif kind == "agent_start":
            RESPONSE_SEQ += 1
            DUQUE_SPEAKING = False
            SPEECH_STARTED_AT = None
            touch()
            if not SHUTTING_DOWN:
                hud("processando", "Processando comando...")
        elif kind == "agent_end":
            # Em segundo plano: enquanto o áudio toca, eventos de interrupção
            # (fala do usuário) precisam continuar sendo tratados.
            spawn(after_response(RESPONSE_SEQ))
        elif kind == "error":
            error = getattr(event, "error", event)
            if is_benign_error(error):
                _kind, code, _message = error_details(error)
                log(f"[REALTIME] aviso ignorado: {code or error}")
                continue
            log(f"[REALTIME] erro: {error}")
            if is_fatal_error(error):
                if SHUTDOWN_EVENT:
                    SHUTDOWN_EVENT.set()
                return


async def realtime_session() -> None:
    global LOOP, MIC_QUEUE, SHUTDOWN_EVENT, REALTIME, MIC_ACTIVE, SESSION, TRACKER
    global DUQUE_SPEAKING, SHUTTING_DOWN, SPEECH_STARTED_AT, CURRENT_ITEM, RESPONSE_SEQ
    LOOP = asyncio.get_running_loop()
    MIC_QUEUE = asyncio.Queue(maxsize=100)
    SHUTDOWN_EVENT = asyncio.Event()
    FENCE.new_session()
    REALTIME = True
    MIC_ACTIVE = False
    SHUTTING_DOWN = False
    DUQUE_SPEAKING = False
    CURRENT_ITEM = None
    RESPONSE_SEQ = 0
    touch()
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
            idle_task = asyncio.create_task(idle_watchdog())
            done, pending = await asyncio.wait(
                (mic_task, event_task, shutdown_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            pending.add(idle_task)
            pending.update(BACKGROUND_TASKS)
            for task in pending:
                task.cancel()
            for task in pending:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    log(f"[REALTIME] tarefa pendente terminou com erro: {exc}")
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
        hud("standby", "Sistema online", mode="texto")


def match_input_device(name: str) -> int | None:
    """Índice do sounddevice para o microfone que o PvRecorder chama de ``name``.

    O sounddevice (MME) corta nomes em 31 caracteres; por isso vale prefixo.
    """
    wanted = (name or "").strip().casefold()
    if not wanted:
        return None
    try:
        devices = sd.query_devices()
    except Exception:
        return None
    for index, device in enumerate(cast(list[dict[str, Any]], list(devices))):
        candidate = str(device.get("name", "")).strip().casefold()
        if device.get("max_input_channels", 0) > 0 and candidate and (
            wanted == candidate or wanted.startswith(candidate) or candidate.startswith(wanted)
        ):
            return index
    return None


def voice_unavailable(reason: str) -> RuntimeError:
    hud("erro", f"Voz indisponível: {reason}", mode="texto")
    return RuntimeError(reason)


def wake_loop() -> None:
    global MICROFONE
    if not os.getenv("OPENAI_API_KEY"):
        raise voice_unavailable("OPENAI_API_KEY não encontrada")

    openwakeword_file = openwakeword.__file__
    if not openwakeword_file:
        raise voice_unavailable("arquivo do openwakeword não foi localizado")

    wake_model_path = (
        Path(openwakeword_file).resolve().parent
        / "resources"
        / "models"
        / "hey_jarvis_v0.1.onnx"
    )
    if not wake_model_path.exists():
        raise voice_unavailable(f"modelo wake word não encontrado: {wake_model_path}")

    devices = PvRecorder.get_available_devices()
    log(f"[WAKE] dispositivos PvRecorder: {devices}")
    if not devices:
        raise voice_unavailable("nenhum dispositivo de entrada foi encontrado pelo PvRecorder")
    wake_mic = WAKE_MICROFONE
    if wake_mic >= len(devices):
        if WAKE_MIC_OVERRIDE is not None:
            raise voice_unavailable(
                f"DUQUE_WAKE_MIC={wake_mic} inválido; existem apenas {len(devices)} dispositivo(s)"
            )
        wake_mic = -1

    selected_name = devices[wake_mic] if wake_mic >= 0 else ""
    if MIC_OVERRIDE is None:
        MICROFONE = match_input_device(selected_name)
    log(
        f"[WAKE] inicializando | modelo={wake_model_path.name} | threshold={WAKE_THRESHOLD} | "
        f"frame={FRAME_LENGTH} | wake_mic={wake_mic} ({selected_name or 'padrão do sistema'!r}) | "
        f"mic_conversa={MICROFONE if MICROFONE is not None else 'padrão do sistema'}"
    )

    wake_model = Model(
        wakeword_models=[str(wake_model_path)],
        inference_framework="onnx",
    )
    log("[WAKE] modelo carregado com sucesso.")
    hud("standby", "Sistema online", mode="texto")

    last_wake = 0.0
    recovering = False
    while True:
        recorder = None
        try:
            recorder = PvRecorder(
                frame_length=FRAME_LENGTH,
                device_index=wake_mic,
            )
            recorder.start()
            log(
                f'[WAKE] ativo: "Hey Jarvis" | modelo={WAKEWORD_MODEL_NAME} | '
                f"threshold={WAKE_THRESHOLD} | mic={wake_mic} | "
                f"dispositivo={recorder.selected_device!r}"
            )
            if recovering:
                recovering = False
                hud("standby", "Sistema online", mode="texto")

            while True:
                frame = np.asarray(recorder.read(), dtype=np.int16)
                predictions = cast(dict[str, float], wake_model.predict(frame))
                confidence = predictions.get(
                    WAKEWORD,
                    predictions.get(WAKEWORD_MODEL_NAME, 0.0),
                )
                now = time.perf_counter()

                if confidence >= WAKE_THRESHOLD and now - last_wake >= WAKE_COOLDOWN:
                    log(f"[WAKE] detectado (confiança={confidence:.2f})")
                    recorder.stop()
                    recorder.delete()
                    recorder = None
                    asyncio.run(realtime_session())
                    # O buffer do modelo ainda guarda o "Hey Jarvis" antigo (e a
                    # voz do Duque); sem limpar, o wake word dispara de novo.
                    wake_model.reset()
                    last_wake = time.perf_counter()
                    break

        except KeyboardInterrupt:
            return
        except Exception as exc:
            log(
                f"[WAKE] loop falhou: {type(exc).__name__}: {exc!r}. "
                "Tentando novamente em 2s."
            )
            recovering = True
            hud("erro", "Wake word temporariamente indisponível", mode="texto")
            time.sleep(2.0)
        finally:
            if recorder:
                try:
                    recorder.stop()
                    recorder.delete()
                except Exception:
                    pass


if __name__ == "__main__":
    log(
        f"Duque Realtime | modelo={MODEL} | voz={VOICE} | "
        f"processamento={'on' if VOICE_PROCESSING else 'off'}"
    )
    wake_loop()
