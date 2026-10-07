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
from agents.realtime.model_inputs import RealtimeModelSendRawMessage
from agent.duque_realtime import duque_realtime, refresh_instructions
from core.emergency import emergency, is_pause_command
from core.voice_bridge import bridge
from voice import local_wake, local_runtime
from voice.devices import match_input_device, pick_wake_device
from voice.conversation_flow import VoiceFlow, greeting_reply
from voice.gate import addressed, is_echo
from voice.session import PlaybackFence
from voice.transcripts import speech_from_event

# Runtime de voz ÚNICO do TELEX: ativação (nome "TELEX"; "Hey Jarvis" só de reserva),
# conversa Realtime (OpenAI) e conversa local (voice/local_runtime.py). Antes as
# regras da conversa ficavam num segundo arquivo (duque_wake_v3.py) que trocava
# funções deste aqui em tempo de execução; agora tudo mora neste módulo.

MODEL = os.getenv("DUQUE_REALTIME_MODEL", "gpt-realtime-2.1")
VOICE = os.getenv("DUQUE_VOICE", "cedar")
# Microfone: DUQUE_WAKE_MIC / DUQUE_MIC (o número da lista do diagnóstico, que é a do
# PvRecorder) ou escolha automática. A conversa usa o MESMO microfone, achado pelo nome
# (o sounddevice numera os dispositivos de outro jeito).
WAKE_MICROFONE = -1
WAKE_DEVICE_NAME = ""


def pick_input_device(wake_name: str) -> int | None:
    """Microfone da conversa: o mesmo da wake word (os índices do sounddevice são outros)."""
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
# Quanto áudio antes do "Telex" é guardado para não perder o começo do pedido.
PREROLL_FRAMES = 30  # 30 x 80 ms = 2,4 s
PITCH_SEMITONES = float(os.getenv("DUQUE_PITCH", "-2.0"))
VOICE_SPEED = float(os.getenv("DUQUE_VOICE_SPEED", "0.96"))
# Colchão de áudio: a fala só começa a tocar com ~180 ms guardados. Sem ele,
# qualquer atraso da rede virava um "buraco" no meio da frase (voz picotada).
PREBUFFER_BYTES = int(24000 * 2 * float(os.getenv("DUQUE_PREBUFFER_MS", "180")) / 1000)
PREBUFFER_MAX_WAIT = 0.35
VOICE_PROCESSING = os.getenv("DUQUE_VOICE_PROCESSING", "0").casefold() in {"1", "true", "yes", "on"}

FAREWELLS = (
    "até mais telex", "até logo telex", "tchau telex", "pode dormir telex",
    "até mais, telex", "até logo, telex", "tchau, telex", "pode dormir, telex",
)
# Um nome só: "Hey Jarvis" fica desligado. Ele só volta sozinho, como reserva,
# se a ativação pelo nome "TELEX" não puder ser carregada (DUQUE_HEY_JARVIS=1 força).
HEY_JARVIS = os.getenv("DUQUE_HEY_JARVIS", "0").casefold() not in {"0", "false", "off", "no", "nao", "não"}

voice_board = Pedalboard([
    HighpassFilter(cutoff_frequency_hz=60.0),
    LowShelfFilter(cutoff_frequency_hz=180.0, gain_db=3.0),
    Compressor(threshold_db=-24.0, ratio=2.5, attack_ms=10.0, release_ms=120.0),
    Gain(gain_db=-1.0),
])

class TelexRealtimeModel(OpenAIRealtimeWebSocketModel):
    """Modelo de voz que NÃO se interrompe sozinho.

    A biblioteca da OpenAI, ao detectar qualquer som no microfone
    ("input_audio_buffer.speech_started"), parava o áudio, truncava e CANCELAVA a
    resposta — inclusive com o eco da própria voz do TELEX ou barulho de fundo.
    Aqui esse evento só é repassado (para o HUD); quem decide interromper é o
    portão (voice/gate.py), e só quando ouve "Telex".
    """

    async def _handle_ws_event(self, event):  # type: ignore[override]
        if isinstance(event, dict) and event.get("type") == "input_audio_buffer.speech_started":
            try:
                from agents.realtime.model_events import RealtimeModelRawServerEvent

                await self._emit_event(RealtimeModelRawServerEvent(data=event))  # type: ignore[attr-defined]
            except Exception:
                pass
            return
        await super()._handle_ws_event(event)  # type: ignore[misc]


def new_model() -> OpenAIRealtimeWebSocketModel:
    # Um modelo novo por sessão: o objeto guarda o último item falado e, se fosse
    # reaproveitado, a sessão seguinte pedia um item que não existe mais
    # ("item_retrieve_invalid_item_id") e caía na hora.
    model_class = TelexRealtimeModel if hasattr(OpenAIRealtimeWebSocketModel, "_handle_ws_event") else OpenAIRealtimeWebSocketModel
    return model_class(transport_config={
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
                            "prefix_padding_ms": 300, "silence_duration_ms": 900,
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
# Regras da conversa (voice/conversation_flow.py): saudação, "Telex", interrupção.
FLOW = VoiceFlow()
LAST_ACTIVITY = time.monotonic()
LAST_ASSISTANT_TEXT = ""
# Saudação (legado): a ativação agora é só pelo nome, então ela não é mais disparada.
GREETING_TURN = False
# Uma resposta do modelo em andamento (entre agent_start e agent_end).
RESPONDING = False
TURN = 0
# Última resposta falada: o que o microfone ouvir parecido logo depois é eco.
RECENT_SPOKEN = ""
RECENT_SPOKEN_AT = 0.0
ECHO_SECONDS = 6.0
# Trava de segurança: sem NENHUMA atividade por este tempo (ex.: o fim de uma
# resposta nunca chegou), a conversa fecha mesmo fora do standby, em vez de
# ficar com o microfone aberto para a OpenAI para sempre.
STUCK_SECONDS = max(IDLE_SECONDS * 5, 300.0) if IDLE_SECONDS > 0 else 0.0
# Tarefas assíncronas em andamento (referência forte + erro registrado no log).
TASKS: set[asyncio.Task] = set()


def touch() -> None:
    """Marca atividade (pedido aceito, fala ou ferramenta) para o tempo de espera."""
    global LAST_ACTIVITY
    LAST_ACTIVITY = time.monotonic()


def idle_expired(now: float | None = None) -> bool:
    if IDLE_SECONDS <= 0:
        return False
    elapsed = (time.monotonic() if now is None else now) - LAST_ACTIVITY
    if STUCK_SECONDS and elapsed >= STUCK_SECONDS:
        return True
    if DUQUE_SPEAKING or RESPONDING or FLOW.state != "standby" or FLOW.user_talking:
        return False
    return elapsed >= IDLE_SECONDS


def spawn(coro: Coroutine[Any, Any, Any], name: str = "") -> asyncio.Task:
    """create_task que guarda a referência (o asyncio só guarda uma fraca) e registra erros."""
    task = asyncio.get_running_loop().create_task(coro, name=name or None)
    TASKS.add(task)

    def done(finished: asyncio.Task) -> None:
        TASKS.discard(finished)
        if not finished.cancelled() and finished.exception() is not None:
            log(f"[VOZ] tarefa {finished.get_name()} falhou: {finished.exception()!r}")

    task.add_done_callback(done)
    return task


def spawn_threadsafe(loop: asyncio.AbstractEventLoop | None, factory: Any, name: str = "") -> bool:
    """Agenda ``factory()`` (que cria a corrotina) no laço da conversa, vindo de outra thread."""
    if loop is None or loop.is_closed():
        return False
    try:
        loop.call_soon_threadsafe(lambda: spawn(factory(), name))
        return True
    except RuntimeError:  # laço já fechado
        return False


def hud_waiting() -> None:
    hud("standby", 'Em espera — diga "Telex"')


_HUD_QUEUE: queue.Queue[tuple[str, str]] = queue.Queue(maxsize=64)
_HUD_THREAD: threading.Thread | None = None
_HUD_LOCK = threading.Lock()


def _post_hud(state: str, task: str) -> None:
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


def _hud_worker() -> None:
    while True:
        state, task = _HUD_QUEUE.get()
        _post_hud(state, task)


def hud(state: str, task: str = "") -> None:
    """Atualiza o HUD sem bloquear: o POST sai numa thread própria, na ordem.

    Antes o POST (até 0,5 s) rodava dentro do laço da conversa e atrasava o áudio
    e os eventos sempre que o servidor demorava.
    """
    global _HUD_THREAD
    with _HUD_LOCK:
        if _HUD_THREAD is None or not _HUD_THREAD.is_alive():
            _HUD_THREAD = threading.Thread(target=_hud_worker, name="telex-hud", daemon=True)
            _HUD_THREAD.start()
    try:
        _HUD_QUEUE.put_nowait((state, task))
    except queue.Full:
        pass  # HUD fora do ar: o estado é descartável


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
    if not item_id.startswith("telex-"):
        # Só falas do modelo: o bipe ("telex-chime") virava o "item atual" e, ao
        # interromper, entrava na lista de cancelados — e os bipes seguintes sumiam.
        with state_lock:
            CURRENT_ITEM = item_id


def queued_bytes() -> int:
    with AUDIO_LOCK:
        return sum(len(chunk[2]) for chunk in AUDIO)


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
            if item_id.startswith("telex-"):
                continue  # bipe local: o modelo não conhece esse item
            try:
                TRACKER.on_play_bytes(item_id, content_index, chunk)
            except Exception:
                pass


def microphone_callback(indata, _frames, _time_info, status) -> None:
    global VAD_COUNT, LAST_INTERRUPT
    if status:
        log(f"[MIC] {status}")
    loop = LOOP
    if not REALTIME or not MIC_ACTIVE or loop is None or MIC_QUEUE is None:
        return
    audio = indata.copy().tobytes()
    # Só o nome "Telex" interrompe (voice/conversation_flow.py); barulho não corta a fala.
    if LOCAL_VAD_INTERRUPT and DUQUE_SPEAKING and not SHUTTING_DOWN:
        now = time.perf_counter()
        if SPEECH_STARTED_AT is None or now - SPEECH_STARTED_AT >= LOCAL_VAD_IGNORE_AFTER_SPEECH:
            VAD_COUNT = VAD_COUNT + 1 if rms(audio) >= LOCAL_VAD_THRESHOLD else 0
            if VAD_COUNT >= LOCAL_VAD_BLOCKS and now - LAST_INTERRUPT >= LOCAL_VAD_COOLDOWN:
                VAD_COUNT = 0
                LAST_INTERRUPT = now
                spawn_threadsafe(loop, interrupt_session, "interromper")

    def enqueue() -> None:
        queue_ = MIC_QUEUE
        if queue_ is None or not REALTIME or not MIC_ACTIVE or SHUTTING_DOWN:
            return
        try:
            queue_.put_nowait(audio)
        except asyncio.QueueFull:
            pass  # rede lenta ou sessão caindo: o trecho atual é descartável

    try:
        loop.call_soon_threadsafe(enqueue)
    except RuntimeError:
        pass  # laço já fechado


async def interrupt_session() -> None:
    if SESSION is None or SHUTTING_DOWN:
        return
    # A resposta interrompida não pode voltar a tocar com os trechos que ainda
    # estão chegando pela rede (antes só o evento audio_interrupted cancelava).
    item_id = CURRENT_ITEM
    if item_id:
        with CANCELLED_LOCK:
            CANCELLED.add(item_id)
    clear_audio()
    reset_voice_processor()
    try:
        await SESSION.interrupt()
    except Exception as exc:
        log(f"[VAD] interrupção falhou: {exc}")


async def finish_shutdown(reply_wait: float = 8.0, reply_limit: float = 30.0) -> None:
    """Fecha a conversa depois que a despedida foi falada por inteiro.

    Antes este passo esperava só o áudio JÁ recebido: como a despedida ainda nem
    tinha começado, a sessão fechava na hora e cortava o "Até logo, Du".
    """
    started = time.monotonic()
    while not (RESPONDING or DUQUE_SPEAKING) and time.monotonic() - started < reply_wait:
        await asyncio.sleep(0.1)
    while (RESPONDING or DUQUE_SPEAKING) and time.monotonic() - started < reply_limit:
        if not RESPONDING and PLAYBACK_DRAINED.is_set():
            break
        await asyncio.sleep(0.1)
    await wait_playback()
    if SHUTDOWN_EVENT:
        SHUTDOWN_EVENT.set()


def request_shutdown() -> None:
    """Encerramento: corta a entrada na hora, mas deixa a despedida terminar."""
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
    if LOOP is not None and SHUTDOWN_EVENT is not None:
        spawn_threadsafe(LOOP, finish_shutdown, "despedida")


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
    """Fecha a conversa depois de um tempo em standby, sem ser chamado."""
    # Não termina durante o encerramento: esta tarefa é vigiada pela sessão e, se
    # acabasse, a conversa fechava na hora e cortava a despedida.
    while REALTIME:
        await asyncio.sleep(1.0)
        if SHUTTING_DOWN:
            continue
        if idle_expired():
            if FLOW.state == "standby" and not (DUQUE_SPEAKING or RESPONDING):
                log(f"[GATE] {IDLE_SECONDS:.0f}s sem ser chamado; voltando ao standby.")
            else:
                log(f"[GATE] {STUCK_SECONDS:.0f}s sem nenhuma atividade (estado {FLOW.state}); fechando a conversa.")
            return


def send_text_to_session(text: str) -> bool:
    """Texto digitado no HUD durante a conversa de voz: entra na mesma sessão."""
    loop, session = LOOP, SESSION
    if loop is None or session is None or SHUTTING_DOWN:
        return False
    touch()

    async def deliver() -> None:
        if DUQUE_SPEAKING:
            await interrupt_session()
        try:
            await session.send_message(text)
        except Exception as exc:
            log(f"[REALTIME] envio de texto falhou: {exc}")

    return spawn_threadsafe(loop, deliver, "texto-digitado")


def stop_speech_from_core() -> None:
    spawn_threadsafe(LOOP, interrupt_session, "parar-fala")


# Dois tons subindo = "estou ouvindo"; dois tons descendo = "parei, estou executando".
CHIME_LISTEN = ((880.0, 0.07), (1320.0, 0.09))
CHIME_DONE = ((1320.0, 0.07), (660.0, 0.11))


def chime_audio(tones: tuple = CHIME_LISTEN) -> bytes:
    """Bipe curto e suave, sem falar nada."""
    pieces = []
    for freq, length in tones:
        t = np.arange(int(SAMPLE_RATE * length)) / SAMPLE_RATE
        envelope = np.minimum(1.0, np.minimum(t, t[::-1]) / 0.01)
        pieces.append(0.18 * envelope * np.sin(2 * np.pi * freq * t))
        pieces.append(np.zeros(int(SAMPLE_RATE * 0.02)))
    return (np.concatenate(pieces) * 32767).astype(np.int16).tobytes()


def _play_tone(tones: tuple, label: str) -> None:
    try:
        enqueue_audio(chime_audio(tones), f"telex-{label}", 0)
    except Exception as exc:
        log(f"[VOZ] bipe falhou: {exc}")


def play_chime() -> None:
    _play_tone(CHIME_LISTEN, "chime")


def play_chime_blocking() -> None:
    """Bipe "estou ouvindo" da conversa local: toca direto e só volta quando acabou
    (o microfone não pode ouvir o próprio bipe)."""
    try:
        samples = np.frombuffer(chime_audio(CHIME_LISTEN), dtype=np.int16)
        sd.play(samples, SAMPLE_RATE)
        # Sem sd.wait(): ele travava para sempre se o alto-falante sumisse.
        time.sleep(len(samples) / SAMPLE_RATE + 0.05)
        sd.stop()
    except Exception as exc:
        log(f"[VOZ] bipe falhou: {exc}")


def play_done() -> None:
    """Som de "parei de ouvir, estou executando"."""
    _play_tone(CHIME_DONE, "done")


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

    spawn_threadsafe(loop, close, "encerrar")


def send_greeting(greeting: str) -> None:
    """Entrega o "Bom dia, TELEX" à conversa: ele responde e já fica ouvindo."""
    global GREETING_TURN
    loop, session = LOOP, SESSION
    if loop is None or session is None:
        return
    GREETING_TURN = True
    FLOW.on_speaking()
    bridge.record("user", greeting, "voz")
    reply = greeting_reply(greeting)

    async def deliver() -> None:
        try:
            await session.send_message(f"{greeting} (Responda exatamente, e só isto: \"{reply}\")")
        except Exception as exc:
            log(f"[REALTIME] saudação não enviada: {exc}")

    spawn_threadsafe(loop, deliver, "saudacao")


async def wait_playback(stall_seconds: float = 3.0) -> None:
    """Espera o alto-falante tocar tudo o que está na fila.

    Nunca espera para sempre: se o dispositivo de saída sumiu (fone desconectado,
    driver travado), a fila para de andar; depois de ``stall_seconds`` sem progresso
    o resto é descartado e a conversa segue (antes ela travava para sempre e a
    ativação por voz nunca mais voltava).
    """
    last = queued_bytes()
    last_change = time.monotonic()
    while not PLAYBACK_DRAINED.is_set():
        await asyncio.to_thread(PLAYBACK_DRAINED.wait, 0.25)
        current = queued_bytes()
        if current != last:
            last, last_change = current, time.monotonic()
        elif time.monotonic() - last_change >= stall_seconds:
            log("[PLAYER] o alto-falante parou de tocar; descartando o áudio que faltava.")
            clear_audio()
            break
    await asyncio.sleep(0.15)


def busy() -> bool:
    return DUQUE_SPEAKING or RESPONDING


def user_transcript(event) -> tuple[str, str] | None:
    """(item_id, texto) de uma fala do Du já transcrita."""
    if getattr(event, "type", "") != "raw_model_event":
        return None
    data = getattr(event, "data", None)
    if getattr(data, "type", "") != "input_audio_transcription_completed":
        return None
    text = str(getattr(data, "transcript", "") or "").strip()
    return (str(getattr(data, "item_id", "") or ""), text) if text else None


def raw_server_type(event) -> str:
    data = getattr(event, "data", None)
    if getattr(data, "type", "") != "raw_server_event":
        return ""
    payload = getattr(data, "data", None)
    return str(payload.get("type", "")) if isinstance(payload, dict) else ""


async def finish_turn(turn: int, spoken: str) -> None:
    """Depois que a fala terminou de tocar: standby (ou escuta curta, conforme as regras)."""
    global DUQUE_SPEAKING, SPEECH_STARTED_AT, RECENT_SPOKEN_AT, GREETING_TURN
    await wait_playback()
    if turn != TURN or RESPONDING or SHUTTING_DOWN or not REALTIME:
        return  # outra resposta já começou
    DUQUE_SPEAKING = False
    SPEECH_STARTED_AT = None
    touch()
    RECENT_SPOKEN_AT = time.monotonic()  # eco possível por mais alguns segundos
    flow = FLOW
    if GREETING_TURN:
        GREETING_TURN = False
        context = await asyncio.to_thread(bridge.context)
        has_previous = len([line for line in context.splitlines() if line.strip()]) > 2
        flow.on_greeting_done(has_previous)
        log("[VOZ] saudação feita; esperando o Du por 5 s")
        hud("ouvindo", "Pode falar...")
        return
    action = flow.on_reply_done(spoken)
    if flow.state in {"listening", "ask_resume"}:
        hud("ouvindo", "Pode responder...")
    elif action == "standby":
        hud_waiting()


async def flow_ticker(session) -> None:
    """Prazos da conversa: fim do pedido, escuta que acabou, pergunta de continuar."""
    flow = FLOW
    while REALTIME:  # (vigiada pela sessão: não pode terminar no encerramento)
        await asyncio.sleep(0.2)
        if SHUTTING_DOWN:
            continue
        action = flow.tick()
        if action == "respond":
            text = flow.take_collected()
            log(f"[VOZ] pedido completo: {text[:80]!r}")
            play_done()  # "parei de ouvir, estou executando"
            if is_farewell(text):
                request_shutdown()
            hud("processando", "Processando comando...")
            await respond_now(session)
        elif action == "ask_resume":
            log("[VOZ] silêncio após a saudação; perguntando se continua de onde parou")
            try:
                await session.send_message(
                    "(O Du ficou em silêncio depois da saudação.) Pergunte só, sem mais nada: "
                    "\"Quer que eu continue de onde parei?\""
                )
            except Exception as exc:
                log(f"[VOZ] pergunta não enviada: {exc}")
        elif action == "standby":
            log("[VOZ] sem fala; standby")
            hud_waiting()


async def handle_user_speech(session, item_id: str, text: str) -> None:
    """Aplica as regras de voice/conversation_flow.py a uma fala transcrita."""
    global DUQUE_SPEAKING
    flow = FLOW
    if busy() and flow.state != "speaking":
        flow.on_speaking()
    short = text if len(text) <= 70 else text[:67] + "..."
    if (addressed(text) or flow.state != "standby") and is_pause_command(text):
        # "Telex, pausa tudo": para tudo e guarda onde parou (core/emergency.py).
        log(f"[GATE] pausa de emergência: {short!r}")
        await drop_item(session, item_id)
        await asyncio.to_thread(
            post_server, "/api/emergencia", {"acao": "pausar", "origem": "voz"}
        )
        return
    recent = RECENT_SPOKEN if time.monotonic() - RECENT_SPOKEN_AT < ECHO_SECONDS else ""
    if is_echo(text, (recent + " " + LAST_ASSISTANT_TEXT).strip()) and not addressed(text):
        log(f"[GATE] ignore (eco da própria voz): {short!r}")
        await drop_item(session, item_id)
        return
    state = flow.state
    action = flow.on_transcript(text)
    log(f"[GATE] {action} (estado {state}): {short!r}")
    if action == "ignore":
        await drop_item(session, item_id)
        return
    touch()
    if action in {"interrupt_and_listen", "interrupt_and_collect"}:
        await interrupt_session()
        DUQUE_SPEAKING = False
    if action in {"chime", "interrupt_and_listen"}:
        await drop_item(session, item_id)
        play_chime()
        hud("ouvindo", "Pode falar...")
        return
    if action == "sleep":
        await drop_item(session, item_id)
        end_session_now("repousar")
        return
    if action == "standby":
        await drop_item(session, item_id)
        hud_waiting()
        return
    if action == "resume":
        await drop_item(session, item_id)
        await asyncio.to_thread(bridge.record, "user", text, "voz")
        try:
            await session.send_message("Sim, continue de onde paramos.")
        except Exception as exc:
            log(f"[VOZ] não consegui continuar: {exc}")
        return
    # collect / interrupt_and_collect: guarda e responde quando ele terminar de falar.
    await asyncio.to_thread(bridge.record, "user", text, "voz")
    hud("ouvindo", "Escutando você...")


async def receive_events(session) -> None:
    """Consumidor de eventos sem despejar deltas de áudio Base64 no terminal."""
    global RESPONDING, TURN, RECENT_SPOKEN, RECENT_SPOKEN_AT
    global DUQUE_SPEAKING, SPEECH_STARTED_AT, LAST_ASSISTANT_TEXT
    DUQUE_SPEAKING = False
    SPEECH_STARTED_AT = None
    RESPONDING = False

    async for event in session:
        if not REALTIME:
            return
        kind = getattr(event, "type", "")

        heard = user_transcript(event)
        if heard:
            await handle_user_speech(session, *heard)
            continue

        # Registra as falas do Duque na conversa única (texto + voz). As do Du só
        # entram quando o portão aceita (som de fundo fica de fora).
        speech = speech_from_event(event)
        if speech and speech[0] == "assistant":
            LAST_ASSISTANT_TEXT = speech[1]
            if not is_announcement(speech[1]):  # o aviso já está na conversa
                await asyncio.to_thread(bridge.record, "assistant", speech[1], "voz")

        if kind == "tool_start":
            touch()
            hud("executando", "Executando pedido...")
            continue
        if kind == "tool_end":
            touch()
            hud("processando", "Resultado recebido")
            continue

        if kind == "raw_model_event":
            server_type = raw_server_type(event)
            if server_type == "input_audio_buffer.speech_started" and not SHUTTING_DOWN:
                FLOW.on_speech_started()
                if FLOW.state in {"listening", "collecting", "ask_resume"}:
                    hud("ouvindo", "Escutando você...")
            elif server_type == "input_audio_buffer.speech_stopped":
                FLOW.on_speech_stopped()

        elif kind == "audio":
            item_id = event.audio.item_id
            if cancelled(item_id):
                continue
            allow_shutdown = SHUTTING_DOWN
            generation = FENCE.state.generation
            if not FENCE.can_enqueue(
                generation,
                item_id,
                allow_shutdown=allow_shutdown,
            ):
                continue
            touch()
            if not DUQUE_SPEAKING:
                DUQUE_SPEAKING = True
                FLOW.on_speaking()
                SPEECH_STARTED_AT = time.perf_counter()
                hud("falando", "TELEX falando...")
            enqueue_audio(
                event.audio.data,
                item_id,
                event.audio.content_index,
                allow_shutdown=allow_shutdown,
            )

        elif kind == "audio_interrupted":
            # Só vem daqui quando NÓS interrompemos (ouviu "Telex"): o modelo do
            # TELEX não se interrompe mais sozinho com som de fundo.
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

        elif kind == "agent_start":
            TURN += 1
            RESPONDING = True
            FLOW.on_speaking()
            DUQUE_SPEAKING = False
            SPEECH_STARTED_AT = None
            touch()
            if not SHUTTING_DOWN:
                hud("processando", "Processando comando...")

        elif kind == "audio_end":
            pass

        elif kind == "agent_end":
            RESPONDING = False
            if SHUTTING_DOWN:
                await wait_playback()
                DUQUE_SPEAKING = False
                if SHUTDOWN_EVENT:
                    SHUTDOWN_EVENT.set()
                return
            # Não espera o áudio terminar aqui: o laço precisa continuar lendo
            # eventos para ouvir "Telex, stop" no meio de uma explicação.
            spoken = LAST_ASSISTANT_TEXT
            LAST_ASSISTANT_TEXT = ""
            RECENT_SPOKEN, RECENT_SPOKEN_AT = spoken, time.monotonic() + 30  # vale até tocar tudo
            spawn(finish_turn(TURN, spoken), "fim-da-fala")

        elif kind == "error":
            # Erros do servidor (ex.: resposta já em andamento) não derrubam a
            # conversa; uma queda real da conexão encerra o laço sozinha.
            log(f"[REALTIME] erro: {getattr(event, 'error', event)}")


def resample_16k_to_24k(pcm: bytes) -> bytes:
    """Áudio do microfone da ativação (16 kHz) no formato da conversa (24 kHz)."""
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    if not len(samples):
        return b""
    target = np.linspace(0, len(samples) - 1, int(len(samples) * 1.5))
    return np.interp(target, np.arange(len(samples)), samples).astype(np.int16).tobytes()


def abrir_interface_na_ativacao() -> None:
    """Quando o TELEX roda oculto (iniciou com o Windows), mostra a interface ao ser ativado.

    core/hud.py só abre uma aba se nenhum HUD estiver conectado (e recusa uma
    segunda abertura em seguida): nada de uma aba nova a cada "TELEX".
    """
    if os.getenv("DUQUE_START_HIDDEN", "0").casefold() not in {"1", "true", "yes", "on", "sim"}:
        return

    def abrir() -> None:
        try:
            from core.hud import abrir_hud

            abrir_hud(SERVIDOR, log=log)
        except Exception as exc:
            log(f"[VOZ] não consegui abrir a interface: {exc}")

    threading.Thread(target=abrir, name="telex-interface-ativacao", daemon=True).start()


# Avisos do núcleo (lembretes, Forja, pausa) durante uma conversa de voz: o HUD fica
# calado para não haver duas vozes, e quem fala é a própria conversa.
ANNOUNCED: deque[str] = deque(maxlen=8)


def announce(text: str) -> bool:
    """Fala um aviso na conversa de voz ativa. False se não há conversa para falar."""
    loop, session = LOOP, SESSION
    text = (text or "").strip()
    if loop is None or session is None or SHUTTING_DOWN or not text:
        return False
    ANNOUNCED.append(text)

    async def deliver() -> None:
        deadline = time.monotonic() + 20.0
        while busy() and time.monotonic() < deadline:  # não atropela a resposta em curso
            await asyncio.sleep(0.2)
        touch()
        try:
            await session.send_message(
                f"(Aviso do sistema, não é fala do Du.) Diga exatamente, e só isto: \"{text}\""
            )
        except Exception as exc:
            log(f"[VOZ] aviso não falado: {exc}")

    return spawn_threadsafe(loop, deliver, "aviso")


def is_announcement(spoken: str) -> bool:
    """A fala do modelo é a leitura de um aviso que o núcleo já registrou na conversa?"""
    for notice in list(ANNOUNCED):
        if is_echo(spoken, notice, threshold=0.7):
            try:
                ANNOUNCED.remove(notice)
            except ValueError:
                pass
            return True
    return False


def _attach_announcer(active: bool) -> None:
    # Gancho opcional da ponte (core/voice_bridge.py): enquanto não existir, o
    # núcleo segue com o comportamento anterior.
    method = getattr(bridge, "attach_announcer" if active else "detach_announcer", None)
    if callable(method):
        try:
            method(announce) if active else method()
        except Exception as exc:
            log(f"[VOZ] gancho de avisos indisponível: {exc}")


async def realtime_session(greeting: str | None = None, *, call: bool = False, preroll: bytes = b"") -> bool:
    """Uma conversa pela OpenAI Realtime. Devolve False se nem chegou a conectar."""
    global LOOP, MIC_QUEUE, SHUTDOWN_EVENT, REALTIME, MIC_ACTIVE, SESSION, TRACKER
    global DUQUE_SPEAKING, SHUTTING_DOWN, SPEECH_STARTED_AT, CURRENT_ITEM, GREETING_TURN
    global RESPONDING, OPENAI_BLOCKED, LAST_ASSISTANT_TEXT
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
    RESPONDING = False
    LAST_ASSISTANT_TEXT = ""
    with CANCELLED_LOCK:
        CANCELLED.clear()
    clear_audio()
    reset_voice_processor()
    FLOW.collected.clear()
    FLOW.user_talking = False
    if greeting:
        FLOW.on_speaking()  # vai responder "Boa tarde, Du. À sua disposição."
    else:
        FLOW.on_call()  # "Telex" / "Hey Jarvis": bipe e escuta
    touch()
    hud("ouvindo", "Escutando você...")
    abrir_interface_na_ativacao()  # TELEX iniciou oculto: ao ser ativado, mostra o HUD
    player = None
    input_stream = None
    connected = False
    started = time.perf_counter()
    try:

        def mark(step: str) -> None:
            log(f"[REALTIME] {step} (+{time.perf_counter() - started:.1f}s)")

        player = sd.RawOutputStream(samplerate=SAMPLE_RATE, channels=CANAIS, dtype="int16", blocksize=BLOCKSIZE, callback=output_callback)
        player.start()
        mark("alto-falante pronto")
        if not greeting:
            play_chime()  # "estou ouvindo"
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
            connected = True
            bridge.attach_session(send_text_to_session, stop_speech_from_core, end_session_now)
            _attach_announcer(True)
            mark("conectado ao modelo de voz")
            input_device = pick_input_device(WAKE_DEVICE_NAME)
            input_stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=CANAIS, dtype=np.int16, device=input_device, blocksize=BLOCKSIZE, callback=microphone_callback)
            if preroll and MIC_QUEUE is not None:
                # O que ele já disse junto com "Telex" ("Telex, que horas são")
                # entra na conversa antes do microfone ao vivo.
                audio = resample_16k_to_24k(preroll)
                step = SAMPLE_RATE // 5 * 2  # 200 ms por pedaço
                for start in range(0, len(audio), step):
                    try:
                        MIC_QUEUE.put_nowait(audio[start:start + step])
                    except asyncio.QueueFull:
                        break
            input_stream.start()
            MIC_ACTIVE = True
            watched = [
                asyncio.create_task(send_microphone(session), name="microfone"),
                asyncio.create_task(receive_events(session), name="eventos"),
                asyncio.create_task(SHUTDOWN_EVENT.wait(), name="encerramento"),
                asyncio.create_task(idle_watch(), name="espera"),
                # Os prazos da conversa também são vigiados: se o laço morrer, a
                # conversa fecha em vez de ficar surda até o tempo de espera.
                asyncio.create_task(flow_ticker(session), name="prazos"),
            ]
            if greeting:
                send_greeting(greeting)
            done, pending = await asyncio.wait(watched, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                log(f"[REALTIME] conversa fechando: tarefa '{task.get_name()}' terminou.")
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
        if any(mark in repr(exc) for mark in ("insufficient_quota", "credit_balance", "invalid_api_key")):
            # Sem créditos (ou chave inválida) na OpenAI: as próximas conversas passam a ser locais.
            OPENAI_BLOCKED = True
            log("[VOZ] OpenAI indisponível (créditos/chave); a partir de agora a conversa de voz é local.")
    finally:
        for task in list(TASKS):
            task.cancel()
        duracao = time.perf_counter() - started
        motivo = "você encerrou" if SHUTTING_DOWN else "a conexão caiu (voltando ao standby)"
        log(f"[VOZ] conversa de voz encerrada após {duracao:.0f}s — {motivo}.")
        bridge.detach_session()
        _attach_announcer(False)
        ANNOUNCED.clear()
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
        RESPONDING = False
        FLOW.state, FLOW.deadline = "standby", None
        FLOW.collected.clear()
        FLOW.user_talking = False
        if emergency.paused:
            hud("standby", "Pausa de emergência")
        else:
            hud("standby", "Sistema online")
    return connected


OPENAI_BLOCKED = False


def _wake_model_path() -> Path:
    openwakeword_file = openwakeword.__file__
    if not openwakeword_file:
        raise RuntimeError("Arquivo do openwakeword não foi localizado")
    path = Path(openwakeword_file).resolve().parent / "resources" / "models" / "hey_jarvis_v0.1.onnx"
    if not path.exists():
        # Instalações em que o modelo não veio junto: baixa na hora (uma vez só).
        log(f"[WAKE] modelo ausente em {path.parent}; baixando agora...")
        try:
            import openwakeword.utils as oww_utils

            oww_utils.download_models(model_names=["hey_jarvis"])
        except Exception as exc:
            log(f"[WAKE] download do modelo falhou: {type(exc).__name__}: {exc}")
    if not path.exists():
        raise RuntimeError(f"Modelo wake word não encontrado: {path}")
    return path


def select_microphone() -> None:
    """Escolhe (de novo) o microfone. Chamado no início e depois de falhas: ao
    conectar/desconectar um fone, o Windows renumera os dispositivos."""
    global WAKE_MICROFONE, WAKE_DEVICE_NAME
    devices = PvRecorder.get_available_devices()
    log(f"[WAKE] dispositivos PvRecorder: {devices}")
    if not devices:
        raise RuntimeError("Nenhum dispositivo de entrada foi encontrado pelo PvRecorder.")
    index, reason = pick_wake_device(devices)
    if index >= len(devices):
        log(f"[WAKE] DUQUE_WAKE_MIC={index} não existe (só há {len(devices)}); usando o padrão do sistema.")
        index, reason = -1, "padrão do sistema (número configurado inválido)"
    WAKE_MICROFONE = index
    WAKE_DEVICE_NAME = devices[index] if index >= 0 else ""
    log(f"[WAKE] microfone {index} ({WAKE_DEVICE_NAME or 'padrão do sistema'}): {reason}")


def local_control(text: str) -> bool:
    """Conversa local: "Telex, pausa tudo" aciona a pausa de emergência de verdade."""
    if is_pause_command(text):
        log("[VOZ-LOCAL] pausa de emergência pedida por voz.")
        post_server("/api/emergencia", {"acao": "pausar", "origem": "voz"})
        return True
    return False


def converse(local_voice: Any, greeting: str | None, action: str, preroll: bytes) -> None:
    """Uma conversa: OpenAI Realtime ou local, com a outra de reserva."""
    call = action == "call"
    has_key = bool(os.getenv("OPENAI_API_KEY"))
    chosen = os.getenv("DUQUE_VOICE", "auto").strip().casefold()
    if local_runtime.voice_mode(has_key, OPENAI_BLOCKED) == "local":
        reason = local_voice.run(greeting, call=call, preroll=preroll)
        if reason == "indisponível" and has_key and not OPENAI_BLOCKED and chosen != "local":
            log("[VOZ] conversa local indisponível; usando a OpenAI desta vez.")
            asyncio.run(realtime_session(greeting, call=call, preroll=preroll))
        elif reason == "indisponível":
            hud("erro", "Voz local indisponível — rode o preparar_local.bat")
        return
    connected = asyncio.run(realtime_session(greeting, call=call, preroll=preroll))
    if not connected and chosen != "openai":
        # Sem internet / OpenAI fora do ar: a mesma ativação vira uma conversa local.
        log("[VOZ] OpenAI não conectou; seguindo com a conversa local.")
        local_voice.run(greeting, call=call, preroll=preroll)


def wake_loop() -> None:
    log("[WAKE] verificando chave, modelo e microfone...")
    if not os.getenv("OPENAI_API_KEY"):
        log("[WAKE] sem OPENAI_API_KEY: a conversa de voz será 100% local (Ollama + Piper/Windows).")

    # Preparação com novas tentativas: sem microfone no boot (fone Bluetooth ainda
    # conectando), a voz antes morria de vez até reiniciar o TELEX.
    while True:
        try:
            wake_model_path = _wake_model_path()
            select_microphone()
            wake_model = Model(wakeword_models=[str(wake_model_path)], inference_framework="onnx")
            break
        except Exception as exc:
            log(f"[WAKE] preparação falhou: {type(exc).__name__}: {exc}. Tentando de novo em 15s.")
            hud("erro", "Ativação por voz indisponível — veja o duque.log")
            time.sleep(15.0)
    log(f"[WAKE] modelo carregado | threshold={WAKE_THRESHOLD} | frame={FRAME_LENGTH}")
    # Ativação pelo nome "TELEX" (local, sem internet).
    local = local_wake.load(log)
    if local is None and not HEY_JARVIS:
        log('[WAKE] AVISO: ativação "TELEX" indisponível; usando "Hey Jarvis" só como reserva até o modelo instalar.')
        hud("erro", 'Ativação "TELEX" indisponível — rode o preparar_duque.bat')
    jarvis_on = HEY_JARVIS or local is None
    hud("standby", "Pausa de emergência" if emergency.paused else "Sistema online")

    local_voice = local_runtime.LocalVoice(
        think=bridge.execute,
        record=lambda role, text: bridge.record(role, text, "voz"),
        log=log,
        hud=hud,
        chime=play_chime_blocking,
        device_index=lambda: WAKE_MICROFONE,
        vosk_model=getattr(local, "model", None),
        control=local_control,
    )
    last_wake = 0.0
    failures = 0
    while True:
        recorder = None
        try:
            recorder = PvRecorder(frame_length=FRAME_LENGTH, device_index=WAKE_MICROFONE)
            recorder.start()
            phrases = '"TELEX"' if local else ""
            if jarvis_on:
                phrases = (phrases + " e " if phrases else "") + '"Hey Jarvis"'
            log(
                f"[WAKE] ativo: {phrases} | mic={WAKE_MICROFONE} | "
                f"dispositivo={recorder.selected_device!r}"
            )
            # Nada do áudio de antes da conversa (ou da própria voz do TELEX) pode
            # sobrar nos buffers e reativar sozinho logo depois.
            if local:
                local.reset()
            try:
                wake_model.reset()
            except Exception:
                pass
            recent: deque[bytes] = deque(maxlen=PREROLL_FRAMES)

            while True:
                frame = np.asarray(recorder.read(), dtype=np.int16)
                failures = 0
                recent.append(frame.tobytes())
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
                if action not in {"wake", "call"}:
                    if emergency.paused:
                        hud("standby", 'Pausa de emergência — diga "Retomar, TELEX"')
                    continue
                preroll = b"".join(recent) if action == "call" else b""
                recorder.stop()
                recorder.delete()
                recorder = None
                converse(local_voice, greeting, action, preroll)
                last_wake = time.perf_counter()  # o intervalo conta do FIM da conversa
                break

        except KeyboardInterrupt:
            return
        except Exception as exc:
            failures += 1
            log(f"[WAKE] loop falhou: {type(exc).__name__}: {exc!r}. Tentando novamente em 2s.")
            hud("erro", "Wake word temporariamente indisponível")
            time.sleep(2.0)
            if failures >= 3:
                try:
                    select_microphone()
                except Exception as select_exc:
                    log(f"[WAKE] não consegui escolher outro microfone: {select_exc}")
        finally:
            if recorder:
                try:
                    recorder.stop()
                    recorder.delete()
                except Exception:
                    pass


if __name__ == "__main__":
    log(f"TELEX Realtime | modelo={MODEL} | voz={VOICE} | processamento={'on' if VOICE_PROCESSING else 'off'}")
    wake_loop()
