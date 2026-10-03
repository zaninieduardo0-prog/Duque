from __future__ import annotations

import asyncio

import duque_wake_v2 as runtime
from core.voice_bridge import bridge
from voice.transcripts import speech_from_event

log = runtime.log

# Exporta o loop de wake word para o launcher, que importa este módulo.
wake_loop = runtime.wake_loop


# Ajuste de identidade do Realtime: o usuário é tratado por "Du".
def patch_identity() -> None:
    agent = runtime.duque_realtime
    instructions = getattr(agent, "instructions", "") or ""
    replacements = {
        'do senhor.': 'do Du.',
        'Chame o usuário de "senhor".': 'Chame o usuário de "Du".',
        'Nunca chame o usuário de "Du".': 'Nunca chame o usuário de "senhor".',
        'Não use "Eduardo", a menos que ele peça.': 'Não use "Eduardo", a menos que ele peça.',
    }
    for old, new in replacements.items():
        instructions = instructions.replace(old, new)
    agent.instructions = instructions


# Evita QueueFull no callback de áudio quando a sessão termina com erro.
def safe_microphone_callback(indata, _frames, _time_info, status) -> None:
    if status:
        runtime.log(f"[MIC] {status}")
    if (
        not runtime.REALTIME
        or not runtime.MIC_ACTIVE
        or runtime.LOOP is None
        or runtime.MIC_QUEUE is None
    ):
        return

    audio = indata.copy().tobytes()
    if runtime.DUQUE_SPEAKING and not runtime.SHUTTING_DOWN:
        now = runtime.time.perf_counter()
        if (
            runtime.SPEECH_STARTED_AT is None
            or now - runtime.SPEECH_STARTED_AT >= runtime.LOCAL_VAD_IGNORE_AFTER_SPEECH
        ):
            runtime.VAD_COUNT = (
                runtime.VAD_COUNT + 1
                if runtime.rms(audio) >= runtime.LOCAL_VAD_THRESHOLD
                else 0
            )
            if (
                runtime.VAD_COUNT >= runtime.LOCAL_VAD_BLOCKS
                and now - runtime.LAST_INTERRUPT >= runtime.LOCAL_VAD_COOLDOWN
            ):
                runtime.VAD_COUNT = 0
                runtime.LAST_INTERRUPT = now
                runtime.LOOP.call_soon_threadsafe(
                    lambda: asyncio.create_task(runtime.interrupt_session())
                )

    def enqueue() -> None:
        queue = runtime.MIC_QUEUE
        if (
            queue is None
            or not runtime.REALTIME
            or not runtime.MIC_ACTIVE
            or runtime.SHUTTING_DOWN
        ):
            return
        try:
            queue.put_nowait(audio)
        except asyncio.QueueFull:
            # Durante uma falha do transporte, o frame atual é descartável.
            pass

    try:
        runtime.LOOP.call_soon_threadsafe(enqueue)
    except Exception:
        pass


async def finish_shutdown() -> None:
    """Finaliza a sessão depois que a despedida realmente terminou."""
    await runtime.wait_playback()
    if runtime.SHUTDOWN_EVENT:
        runtime.SHUTDOWN_EVENT.set()


# Encerramento: corta a entrada imediatamente, mas mantém a sessão viva
# para que a resposta de despedida possa terminar normalmente.
def request_shutdown() -> None:
    if runtime.SHUTTING_DOWN:
        return
    runtime.SHUTTING_DOWN = True
    runtime.MIC_ACTIVE = False
    if runtime.MIC_QUEUE:
        while not runtime.MIC_QUEUE.empty():
            try:
                runtime.MIC_QUEUE.get_nowait()
            except asyncio.QueueEmpty:
                break
    runtime.hud("processando", "Encerrando conversa...")
    runtime.log("Encerramento solicitado; microfone desativado. A despedida continua liberada.")
    if runtime.LOOP is not None and runtime.SHUTDOWN_EVENT is not None:
        runtime.LOOP.call_soon_threadsafe(
            lambda: asyncio.create_task(finish_shutdown())
        )


async def receive_events(session) -> None:
    """Consumidor de eventos sem despejar deltas de áudio Base64 no terminal."""
    runtime.DUQUE_SPEAKING = False
    runtime.SPEECH_STARTED_AT = None

    async for event in session:
        if not runtime.REALTIME:
            return
        kind = getattr(event, "type", "")

        # Registra as falas na conversa única (texto + voz).
        speech = speech_from_event(event)
        if speech:
            role, text = speech
            await runtime.asyncio.to_thread(bridge.record, role, text, "voz")

        if kind == "tool_start":
            runtime.hud("executando", "Executando pedido...")
            continue
        if kind == "tool_end":
            runtime.hud("processando", "Resultado recebido")
            continue

        if kind == "raw_model_event":
            data = getattr(event, "data", None)
            raw_type = getattr(data, "type", "")
            if raw_type == "input_audio_buffer.speech_started" and not runtime.SHUTTING_DOWN:
                runtime.hud("ouvindo", "Escutando você...")
            text = runtime.extract_raw_text(data, raw_type)
            if text and runtime.is_farewell(text):
                request_shutdown()

        elif kind == "history_added":
            text = runtime.extract_text(getattr(event, "item", event)).strip()
            if text and runtime.is_farewell(text):
                request_shutdown()

        elif kind == "audio":
            item_id = event.audio.item_id
            if runtime.cancelled(item_id):
                continue
            allow_shutdown = runtime.SHUTTING_DOWN
            generation = runtime.FENCE.state.generation
            if not runtime.FENCE.can_enqueue(
                generation,
                item_id,
                allow_shutdown=allow_shutdown,
            ):
                continue
            if not runtime.DUQUE_SPEAKING:
                runtime.DUQUE_SPEAKING = True
                runtime.SPEECH_STARTED_AT = runtime.time.perf_counter()
                runtime.hud("falando", "Duque falando...")
            runtime.enqueue_audio(
                event.audio.data,
                item_id,
                event.audio.content_index,
                allow_shutdown=allow_shutdown,
            )

        elif kind == "audio_interrupted":
            item_id = runtime.CURRENT_ITEM
            if item_id:
                with runtime.CANCELLED_LOCK:
                    runtime.CANCELLED.add(item_id)
            runtime.clear_audio()
            runtime.reset_voice_processor()
            runtime.DUQUE_SPEAKING = False
            runtime.SPEECH_STARTED_AT = None
            if runtime.TRACKER:
                try:
                    runtime.TRACKER.on_interrupted()
                except Exception:
                    pass
            if not runtime.SHUTTING_DOWN:
                runtime.hud("ouvindo", "Escutando você...")

        elif kind == "agent_start":
            runtime.DUQUE_SPEAKING = False
            runtime.SPEECH_STARTED_AT = None
            if not runtime.SHUTTING_DOWN:
                runtime.hud("processando", "Processando comando...")

        elif kind == "audio_end":
            pass

        elif kind == "agent_end":
            await runtime.wait_playback()
            runtime.DUQUE_SPEAKING = False
            runtime.SPEECH_STARTED_AT = None
            if runtime.SHUTTING_DOWN:
                if runtime.SHUTDOWN_EVENT:
                    runtime.SHUTDOWN_EVENT.set()
                return
            runtime.hud("ouvindo", "Escutando você...")

        elif kind == "error":
            runtime.log(f"[REALTIME] erro: {getattr(event, 'error', event)}")
            # Garante limpeza completa da sessão após erro do modelo/WebSocket.
            if runtime.SHUTDOWN_EVENT:
                runtime.SHUTDOWN_EVENT.set()
            return


patch_identity()
runtime.request_shutdown = request_shutdown
runtime.receive_events = receive_events
runtime.microphone_callback = safe_microphone_callback


if __name__ == "__main__":
    runtime.log(
        f"Duque Realtime v3 | modelo={runtime.MODEL} | voz={runtime.VOICE} | "
        f"processamento={'on' if runtime.VOICE_PROCESSING else 'off'}"
    )
    runtime.wake_loop()
