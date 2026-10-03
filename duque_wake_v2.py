from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import urllib.request
from typing import cast
from collections import deque
from pathlib import Path

import numpy as np
import openwakeword
import sounddevice as sd
from openwakeword.model import Model
from pvrecorder import PvRecorder
from pedalboard import Compressor, Gain, HighpassFilter, LowShelfFilter, Pedalboard, time_stretch  # pyright: ignore[reportPrivateImportUsage]
from agents.realtime import OpenAIRealtimeWebSocketModel, RealtimeRunner, RealtimePlaybackTracker
from agents.realtime.model_inputs import RealtimeModelSendRawMessage
from agent.duque_realtime import duque_realtime, refresh_instructions
from core.emergency import emergency
from core.voice_bridge import bridge
from voice import local_wake
from voice.devices import match_input_device, pick_wake_device
from voice.gate import ListenGate
from voice.session import PlaybackFence

MODEL = os.getenv("DUQUE_REALTIME_MODEL", "gpt-realtime-2.1")
VOICE = os.getenv("DUQUE_VOICE", "cedar")
# Microfones: definidos por DUQUE_WAKE_MIC / DUQUE_MIC ou escolhidos automaticamente.
MICROFONE: int | None = int(os.environ["DUQUE_MIC"]) if os.getenv("DUQUE_MIC", "").strip() else None
WAKE_MICROFONE = int(os.environ["DUQUE_WAKE_MIC"]) if os.getenv("DUQUE_WAKE_MIC", "").strip() else -1
WAKE_DEVICE_NAME = ""



def pick_input_device(wake_name: str) -> int | None:
    """Microfone da conversa: o mesmo da wake word (os índices do sounddevice são outros)."""
    if MICROFONE is not None:
        return MICROFONE
    try:
        return match_input_device(wake_name, sd.query_devices())
    except Exception:
        return None  # padrão do Windows
SAMPLE_RATE = 24000
CANAIS = 1
BLOCKSIZE = 480
SERVIDOR = "http://127.0.0.1:5000"
WAKEWORD = "hey_jarvis"
WAKEWORD_MODEL_NAME = "hey_jarvis_v0.1"
FRAME_LENGTH = 1280
WAKE_THRESHOLD = float(os.getenv("DUQUE_WAKE_THRESHOLD", "0.5"))
WAKE_COOLDOWN = 2.0
LOCAL_VAD_THRESHOLD = float(os.getenv("DUQUE_VAD_THRESHOLD", "0.045"))
LOCAL_VAD_BLOCKS = 3
LOCAL_VAD_COOLDOWN = 0.8
LOCAL_VAD_IGNORE_AFTER_SPEECH = 0.25
# Interromper a fala por qualquer barulho do microfone. Desligado: agora só o
# nome "Duque" interrompe (ver voice/gate.py). DUQUE_VAD_INTERRUPT=1 religa.
LOCAL_VAD_INTERRUPT = os.getenv("DUQUE_VAD_INTERRUPT", "0").casefold() in {"1", "true", "yes", "on"}
# Sem ser chamado por este tempo, a conversa fecha e volta a esperar "Hey Jarvis".
IDLE_SECONDS = float(os.getenv("DUQUE_VOICE_IDLE", "60"))
PITCH_SEMITONES = float(os.getenv("DUQUE_PITCH", "-2.0"))
VOICE_SPEED = float(os.getenv("DUQUE_VOICE_SPEED", "0.96"))
# Colchão de áudio: a fala só começa a tocar com ~180 ms guardados. Sem ele,
# qualquer atraso da rede virava um "buraco" no meio da frase (voz picotada).
PREBUFFER_BYTES = int(24000 * 2 * float(os.getenv("DUQUE_PREBUFFER_MS", "180")) / 1000)
PREBUFFER_MAX_WAIT = 0.35
VOICE_PROCESSING = os.getenv("DUQUE_VOICE_PROCESSING", "0").casefold() in {"1", "true", "yes", "on"}

FAREWELLS = (
    "até mais duque", "até logo duque", "tchau duque", "pode dormir duque",
    "até mais, duque", "até logo, duque", "tchau, duque", "pode dormir, duque",
    "até mais telex", "até logo telex", "tchau telex", "pode dormir telex",
    "até mais, telex", "até logo, telex", "tchau, telex", "pode dormir, telex",
)
# "Hey Jarvis" continua acordando junto com "Bom dia, TELEX" (DUQUE_HEY_JARVIS=0 desliga).
HEY_JARVIS = os.getenv("DUQUE_HEY_JARVIS", "1").casefold() not in {"0", "false", "off", "no", "nao", "não"}

voice_board = Pedalboard([
    HighpassFilter(cutoff_frequency_hz=60.0),
    LowShelfFilter(cutoff_frequency_hz=180.0, gain_db=3.0),
    Compressor(threshold_db=-24.0, ratio=2.5, attack_ms=10.0, release_ms=120.0),
    Gain(gain_db=-1.0),
])

def new_model() -> OpenAIRealtimeWebSocketModel:
    # Um modelo novo por sessão: o objeto guarda o último item falado e, se fosse
    # reaproveitado, a sessão seguinte pedia um item que não existe mais
    # ("item_retrieve_invalid_item_id") e caía na hora.
    return OpenAIRealtimeWebSocketModel(transport_config={
        "ping_interval": 20.0, "ping_timeout": 60.0,
        "handshake_timeout": 30.0, "max_size": 8 * 1024 * 1024,
    })


def build_runner(voice: str) -> RealtimeRunner:
    """Monta a sessão com a voz escolhida pelo Du (muda sem reiniciar o Duque)."""
    return RealtimeRunner(
        starting_agent=duque_realtime,
        model=new_model(),
        config={
            "model_settings": {
                "model_name": MODEL,
                "audio": {
                    "input": {
                        "format": "pcm16",
                        "noise_reduction": {"type": "far_field"},
                        "transcription": {"model": "gpt-4o-mini-transcribe", "language": "pt"},
                        "turn_detection": {
                            # 500 ms de silêncio antes de responder: com 250 ms ele
                            # cortava o Du no meio da frase. Quem decide se responde
                            # ou interrompe é o portão (voice/gate.py): som de fundo
                            # não gera resposta nem corta a fala do Duque.
                            "type": "server_vad", "threshold": 0.5,
                            "prefix_padding_ms": 300, "silence_duration_ms": 500,
                            "interrupt_response": False, "create_response": False,
                        },
                    },
                    "output": {"format": "pcm16", "voice": voice},
                },
            },
            "tracing_disabled": True,
        },
    )


def current_voice() -> str:
    return bridge.voice(VOICE) or VOICE


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
PLAYING = False
BUFFER_WAIT: float | None = None
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
GATE = ListenGate()
LAST_ACTIVITY = time.monotonic()
LAST_ASSISTANT_TEXT = ""
# A resposta ao "Bom dia, TELEX" deixa a audição aberta para o primeiro pedido.
GREETING_TURN = False


def touch() -> None:
    """Marca atividade (pedido aceito, fala ou ferramenta) para o tempo de espera."""
    global LAST_ACTIVITY
    LAST_ACTIVITY = time.monotonic()


def idle_expired(now: float | None = None) -> bool:
    if IDLE_SECONDS <= 0 or DUQUE_SPEAKING or GATE.is_open:
        return False
    return ((time.monotonic() if now is None else now) - LAST_ACTIVITY) >= IDLE_SECONDS


def hud_waiting() -> None:
    hud("standby", 'Em espera — diga "Telex"')


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


def post_server(path: str, body: dict) -> None:
    try:
        request = urllib.request.Request(
            f"{SERVIDOR}{path}", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=3):
            pass
    except Exception as exc:
        log(f"[WAKE] servidor não respondeu a {path}: {exc}")


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
    global PLAYING, BUFFER_WAIT
    with AUDIO_LOCK:
        AUDIO.clear()
        PLAYING, BUFFER_WAIT = False, None
    with PROCESSING_LOCK:
        PROCESSING.clear()
    FENCE.discard_audio(FENCE.state.generation)
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


def enqueue_audio(data: bytes, item_id: str, content_index: int, *, allow_shutdown: bool = False) -> None:
    global CURRENT_ITEM
    generation = FENCE.state.generation
    if cancelled(item_id) or FENCE.stale(generation, allow_shutdown=allow_shutdown):
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
    global PLAYING, BUFFER_WAIT
    needed = frames * 2 * CANAIS
    result = bytearray()
    played: list[tuple[str, int, bytes]] = []
    consumed: list[int] = []
    with AUDIO_LOCK:
        if not PLAYING and AUDIO:
            queued = sum(len(chunk[2]) for chunk in AUDIO)
            now = time.monotonic()
            BUFFER_WAIT = BUFFER_WAIT or now
            if queued >= PREBUFFER_BYTES or now - BUFFER_WAIT >= PREBUFFER_MAX_WAIT:
                PLAYING, BUFFER_WAIT = True, None
        while PLAYING and len(result) < needed and AUDIO:
            item_id, content_index, data = AUDIO[0]
            if cancelled(item_id):
                AUDIO.popleft()
                consumed.append(FENCE.state.generation)
                continue
            remaining = needed - len(result)
            chunk, rest = data[:remaining], data[remaining:]
            result.extend(chunk)
            if rest:
                AUDIO[0] = (item_id, content_index, rest)
            else:
                AUDIO.popleft()
                consumed.append(FENCE.state.generation)
            played.append((item_id, content_index, chunk))
        if not AUDIO:
            # Acabou (ou faltou áudio): o próximo trecho espera o colchão de novo.
            PLAYING, BUFFER_WAIT = False, None
            with PROCESSING_LOCK:
                processing_empty = not PROCESSING
            if processing_empty:
                PLAYBACK_DRAINED.set()
    if len(result) < needed:
        result.extend(b"\x00" * (needed - len(result)))
    outdata[:] = bytes(result)
    for generation in consumed:
        FENCE.can_consume(generation)
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
    if LOCAL_VAD_INTERRUPT and DUQUE_SPEAKING and not SHUTTING_DOWN:
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
    queue = MIC_QUEUE
    if queue is None:
        return
    while REALTIME:
        try:
            audio = await asyncio.wait_for(queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            continue
        if MIC_ACTIVE and REALTIME and not SHUTTING_DOWN:
            try:
                await session.send_audio(audio)
            except Exception as exc:
                log(f"[MIC] envio falhou: {exc}")
                return


async def respond_now(session) -> None:
    """Pede a resposta à última fala aceita (o servidor não responde sozinho)."""
    touch()
    try:
        await session.model.send_event(RealtimeModelSendRawMessage(message={"type": "response.create"}))
    except Exception as exc:
        log(f"[REALTIME] pedido de resposta falhou: {exc}")


async def drop_item(session, item_id: str | None) -> None:
    """Tira da conversa uma fala de fundo, para o modelo não responder a ela depois."""
    if not item_id:
        return
    try:
        await session.model.send_event(RealtimeModelSendRawMessage(
            message={"type": "conversation.item.delete", "other_data": {"item_id": item_id}}
        ))
    except Exception as exc:
        log(f"[GATE] não consegui descartar a fala de fundo: {exc}")


async def idle_watch() -> None:
    """Fecha a conversa depois de um tempo sem ser chamado (volta ao standby)."""
    while REALTIME and not SHUTTING_DOWN:
        await asyncio.sleep(1.0)
        if idle_expired():
            log(f"[GATE] {IDLE_SECONDS:.0f}s sem ser chamado; voltando ao standby.")
            return


def send_text_to_session(text: str) -> bool:
    """Texto digitado no HUD durante a conversa de voz: entra na mesma sessão."""
    loop, session = LOOP, SESSION
    if loop is None or session is None or SHUTTING_DOWN:
        return False
    touch()
    GATE.close()

    async def deliver() -> None:
        if DUQUE_SPEAKING:
            await interrupt_session()
        try:
            await session.send_message(text)
        except Exception as exc:
            log(f"[REALTIME] envio de texto falhou: {exc}")

    loop.call_soon_threadsafe(lambda: asyncio.create_task(deliver()))
    return True


def stop_speech_from_core() -> None:
    loop = LOOP
    if loop is not None:
        loop.call_soon_threadsafe(lambda: asyncio.create_task(interrupt_session()))


def end_session_now(reason: str = "standby") -> None:
    """Fecha a conversa de voz na hora, sem despedida ("Repousar, Telex", pausa)."""
    global MIC_ACTIVE
    loop, done = LOOP, SHUTDOWN_EVENT
    if loop is None or done is None:
        return
    log(f"[VOZ] conversa encerrada na hora: {reason}")
    MIC_ACTIVE = False

    async def close() -> None:
        await interrupt_session()
        done.set()

    loop.call_soon_threadsafe(lambda: asyncio.create_task(close()))


def send_greeting(greeting: str) -> None:
    """Entrega o "Bom dia, TELEX" à conversa: ele responde e já fica ouvindo."""
    global GREETING_TURN
    loop, session = LOOP, SESSION
    if loop is None or session is None:
        return
    GREETING_TURN = True
    bridge.record("user", greeting, "voz")

    async def deliver() -> None:
        try:
            await session.send_message(greeting)
        except Exception as exc:
            log(f"[REALTIME] saudação não enviada: {exc}")

    loop.call_soon_threadsafe(lambda: asyncio.create_task(deliver()))


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


async def realtime_session(greeting: str | None = None) -> None:
    global LOOP, MIC_QUEUE, SHUTDOWN_EVENT, REALTIME, MIC_ACTIVE, SESSION, TRACKER
    global DUQUE_SPEAKING, SHUTTING_DOWN, SPEECH_STARTED_AT, CURRENT_ITEM, GREETING_TURN
    LOOP = asyncio.get_running_loop()
    MIC_QUEUE = asyncio.Queue(maxsize=100)
    SHUTDOWN_EVENT = asyncio.Event()
    FENCE.new_session()
    REALTIME = True
    MIC_ACTIVE = False
    SHUTTING_DOWN = False
    DUQUE_SPEAKING = False
    CURRENT_ITEM = None
    GREETING_TURN = False
    with CANCELLED_LOCK:
        CANCELLED.clear()
    clear_audio()
    reset_voice_processor()
    GATE.open()
    touch()
    hud("ouvindo", "Escutando você...")
    player = None
    input_stream = None
    try:
        started = time.perf_counter()

        def mark(step: str) -> None:
            log(f"[REALTIME] {step} (+{time.perf_counter() - started:.1f}s)")

        player = sd.RawOutputStream(samplerate=SAMPLE_RATE, channels=CANAIS, dtype="int16", blocksize=BLOCKSIZE, callback=output_callback)
        player.start()
        mark("alto-falante pronto")
        TRACKER = RealtimePlaybackTracker()
        try:
            await asyncio.to_thread(refresh_instructions)
        except Exception as exc:
            log(f"[REALTIME] contexto da conversa indisponível: {exc}")
        voice = await asyncio.to_thread(current_voice)
        mark(f"contexto pronto; voz {voice}")
        session = await build_runner(voice).run(model_config={"playback_tracker": TRACKER})
        async with session:
            SESSION = session
            bridge.attach_session(send_text_to_session, stop_speech_from_core, end_session_now)
            mark("conectado ao modelo de voz")
            input_device = pick_input_device(WAKE_DEVICE_NAME)
            input_stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=CANAIS, dtype=np.int16, device=input_device, blocksize=BLOCKSIZE, callback=microphone_callback)
            input_stream.start()
            MIC_ACTIVE = True
            mic_task = asyncio.create_task(send_microphone(session))
            event_task = asyncio.create_task(receive_events(session))
            shutdown_task = asyncio.create_task(SHUTDOWN_EVENT.wait())
            idle_task = asyncio.create_task(idle_watch())
            if greeting:
                send_greeting(greeting)
            done, pending = await asyncio.wait((mic_task, event_task, shutdown_task, idle_task), return_when=asyncio.FIRST_COMPLETED)
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
        bridge.detach_session()
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
        GREETING_TURN = False
        GATE.close()
        if emergency.paused:
            hud("standby", "Pausa de emergência")
        else:
            hud("standby", "Sistema online")


def wake_loop() -> None:
    global WAKE_MICROFONE, WAKE_DEVICE_NAME
    log("[WAKE] verificando chave, modelo e microfone...")
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY não encontrada no ambiente do Duque")

    openwakeword_file = openwakeword.__file__
    if not openwakeword_file:
        raise RuntimeError("Arquivo do openwakeword não foi localizado")

    wake_model_path = (
        Path(openwakeword_file).resolve().parent
        / "resources"
        / "models"
        / "hey_jarvis_v0.1.onnx"
    )
    if not wake_model_path.exists():
        # Instalações em que o modelo não veio junto: baixa na hora (uma vez só).
        log(f"[WAKE] modelo ausente em {wake_model_path.parent}; baixando agora...")
        try:
            import openwakeword.utils as oww_utils

            oww_utils.download_models(model_names=["hey_jarvis"])
        except Exception as exc:
            log(f"[WAKE] download do modelo falhou: {type(exc).__name__}: {exc}")
    if not wake_model_path.exists():
        raise RuntimeError(f"Modelo wake word não encontrado: {wake_model_path}")
    log("[WAKE] modelo pronto.")

    log(
        f"[WAKE] inicializando | modelo={wake_model_path.name} | "
        f"threshold={WAKE_THRESHOLD} | frame={FRAME_LENGTH} | wake_mic={WAKE_MICROFONE}"
    )

    devices = PvRecorder.get_available_devices()
    log(f"[WAKE] dispositivos PvRecorder: {devices}")
    if not devices:
        raise RuntimeError("Nenhum dispositivo de entrada foi encontrado pelo PvRecorder.")
    WAKE_MICROFONE, reason = pick_wake_device(devices)
    log(f"[WAKE] microfone {WAKE_MICROFONE}: {reason}")
    if WAKE_MICROFONE >= len(devices):
        raise RuntimeError(
            f"DUQUE_WAKE_MIC={WAKE_MICROFONE} inválido; "
            f"existem apenas {len(devices)} dispositivo(s) no PvRecorder."
        )

    selected_name = (
        devices[WAKE_MICROFONE] if WAKE_MICROFONE >= 0 else "padrão do sistema"
    )
    WAKE_DEVICE_NAME = selected_name if WAKE_MICROFONE >= 0 else ""
    log(f"[WAKE] dispositivo selecionado: {selected_name!r}")

    wake_model = Model(
        wakeword_models=[str(wake_model_path)],
        inference_framework="onnx",
    )
    log("[WAKE] modelo carregado com sucesso.")
    # "Bom dia / Boa tarde / Boa noite, TELEX" (local, sem internet).
    local = local_wake.load(log)
    if local is None and not HEY_JARVIS:
        log('[WAKE] sem ativação local; religando "Hey Jarvis" para o TELEX não ficar surdo.')
    jarvis_on = HEY_JARVIS or local is None
    hud("standby", "Pausa de emergência" if emergency.paused else "Sistema online")

    last_wake = 0.0
    while True:
        recorder = None
        try:
            recorder = PvRecorder(
                frame_length=FRAME_LENGTH,
                device_index=WAKE_MICROFONE,
            )
            recorder.start()
            phrases = '"Bom dia, TELEX"' if local else ""
            if jarvis_on:
                phrases = (phrases + ' e ' if phrases else "") + '"Hey Jarvis"'
            log(
                f"[WAKE] ativo: {phrases} | modelo={WAKEWORD_MODEL_NAME} | "
                f"threshold={WAKE_THRESHOLD} | mic={WAKE_MICROFONE} | "
                f"dispositivo={recorder.selected_device!r}"
            )
            if local:
                local.reset()

            while True:
                frame = np.asarray(recorder.read(), dtype=np.int16)
                heard = None
                if local is not None:
                    try:
                        heard = local.feed(frame.tobytes())
                    except Exception as exc:
                        log(f"[WAKE] ativação local falhou e foi desligada: {exc}")
                        local, jarvis_on = None, True
                confidence = 0.0
                if jarvis_on:
                    predictions = cast(dict[str, float], wake_model.predict(frame))
                    confidence = predictions.get(
                        WAKEWORD,
                        predictions.get(WAKEWORD_MODEL_NAME, 0.0),
                    )
                now = time.perf_counter()
                jarvis = confidence >= WAKE_THRESHOLD
                if heard is None and not jarvis:
                    continue
                if now - last_wake < WAKE_COOLDOWN:
                    continue
                action, greeting = local_wake.decide(heard, jarvis, emergency.paused)
                if heard is not None:
                    log(f'[WAKE] ouvi "{heard.phrase}" -> {action}')
                elif jarvis:
                    log(f"[WAKE] Hey Jarvis (confiança={confidence:.2f}) -> {action}")
                if action == "resume":
                    last_wake = now
                    post_server("/api/emergencia", {"acao": "retomar", "origem": "voz"})
                    continue
                if action != "wake":
                    if emergency.paused:
                        hud("standby", 'Pausa de emergência — diga "Retomar, TELEX"')
                    continue
                last_wake = now
                recorder.stop()
                recorder.delete()
                recorder = None
                asyncio.run(realtime_session(greeting))
                break

        except KeyboardInterrupt:
            return
        except Exception as exc:
            log(
                f"[WAKE] loop falhou: {type(exc).__name__}: {exc!r}. "
                "Tentando novamente em 2s."
            )
            hud("erro", "Wake word temporariamente indisponível")
            time.sleep(2.0)
        finally:
            if recorder:
                try:
                    recorder.stop()
                    recorder.delete()
                except Exception:
                    pass
