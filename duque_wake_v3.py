from __future__ import annotations

import asyncio

import duque_wake_v2 as runtime


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


# Encerramento: corta a entrada imediatamente, mas mantém a sessão viva
# para que a resposta de despedida que já estiver sendo gerada/reproduzida
# possa terminar normalmente.
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
    # IMPORTANTE: não chamar FENCE.shutdown() aqui.
    # Isso bloquearia os próprios chunks de áudio da despedida.
    runtime.hud("processando", "Encerrando conversa...")
    runtime.log("Encerramento solicitado; microfone desativado. A despedida continua liberada.")


async def receive_events(session) -> None:
    """Consumidor de eventos sem despejar deltas de áudio Base64 no terminal."""
    runtime.DUQUE_SPEAKING = False
    runtime.SPEECH_STARTED_AT = None

    async for event in session:
        if not runtime.REALTIME:
            return
        kind = getattr(event, "type", "")

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
            if runtime.cancelled(item_id) or runtime.SHUTTING_DOWN:
                continue
            if not runtime.DUQUE_SPEAKING:
                runtime.DUQUE_SPEAKING = True
                runtime.SPEECH_STARTED_AT = runtime.time.perf_counter()
                runtime.hud("falando", "Duque falando...")
            if runtime.FENCE.can_enqueue(runtime.FENCE.state.generation, item_id):
                runtime.enqueue_audio(event.audio.data, item_id, event.audio.content_index)

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
            return


patch_identity()
runtime.request_shutdown = request_shutdown
runtime.receive_events = receive_events


if __name__ == "__main__":
    runtime.log(
        f"Duque Realtime v3 | modelo={runtime.MODEL} | voz={runtime.VOICE} | "
        f"processamento={'on' if runtime.VOICE_PROCESSING else 'off'}"
    )
    runtime.wake_loop()
