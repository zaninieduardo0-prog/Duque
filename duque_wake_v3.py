from __future__ import annotations

import asyncio
import duque_wake_v2 as runtime


# Correção de lifecycle: o pedido de encerramento desliga a entrada, mas não
# invalida a geração de áudio antes da despedida chegar. A sessão só é fechada
# depois que o playback realmente drenou.
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


async def receive_events(session) -> None:
    """Versão corrigida do consumidor de eventos do v2.

    O erro crítico anterior era marcar a sessão como encerrada e, ao mesmo
    tempo, rejeitar todo áudio posterior. Isso descartava a própria despedida.
    Aqui a entrada é bloqueada imediatamente, mas a saída continua até
    `agent_end` + drenagem real do player.
    """
    runtime.DUQUE_SPEAKING = False
    runtime.SPEECH_STARTED_AT = None

    async for event in session:
        if not runtime.REALTIME:
            return
        kind = getattr(event, "type", "")

        if kind == "raw_model_event":
            data = getattr(event, "data", None)
            raw_type = getattr(data, "type", "")
            text = runtime.extract_text(data).strip()
            if raw_type == "input_audio_buffer.speech_started" and not runtime.SHUTTING_DOWN:
                runtime.hud("ouvindo", "Escutando você...")
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
            if not runtime.DUQUE_SPEAKING:
                runtime.DUQUE_SPEAKING = True
                runtime.SPEECH_STARTED_AT = runtime.time.perf_counter()
                runtime.hud("falando", "Duque falando...")
            runtime.FENCE.can_enqueue(runtime.FENCE.state.generation, item_id)
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
            # Não encerra o estado visual aqui: ainda pode haver bytes no
            # processamento local ou na fila do dispositivo.
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


runtime.request_shutdown = request_shutdown
runtime.receive_events = receive_events


if __name__ == "__main__":
    runtime.log(
        f"Duque Realtime v3 | modelo={runtime.MODEL} | voz={runtime.VOICE} | "
        f"processamento={'on' if runtime.VOICE_PROCESSING else 'off'}"
    )
    runtime.wake_loop()
