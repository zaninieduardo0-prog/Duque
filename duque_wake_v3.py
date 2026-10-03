from __future__ import annotations

import asyncio

import duque_wake_v2 as runtime
from core.voice_bridge import bridge
from core.emergency import is_pause_command
from voice.gate import addressed, is_echo
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
    # Só o nome "Duque" interrompe (voice/gate.py); barulho não corta a fala.
    if runtime.LOCAL_VAD_INTERRUPT and runtime.DUQUE_SPEAKING and not runtime.SHUTTING_DOWN:
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


def busy() -> bool:
    return runtime.DUQUE_SPEAKING or RESPONDING


RESPONDING = False
TURN = 0
# Última resposta falada: o que o microfone ouvir parecido logo depois é eco.
RECENT_SPOKEN = ""
RECENT_SPOKEN_AT = 0.0
ECHO_SECONDS = 6.0


async def finish_turn(turn: int, spoken: str) -> None:
    """Depois que a fala terminou de tocar: standby (ou escuta curta, conforme as regras)."""
    await runtime.wait_playback()
    if turn != TURN or RESPONDING or runtime.SHUTTING_DOWN or not runtime.REALTIME:
        return  # outra resposta já começou
    global RECENT_SPOKEN_AT
    runtime.DUQUE_SPEAKING = False
    runtime.SPEECH_STARTED_AT = None
    runtime.touch()
    RECENT_SPOKEN_AT = runtime.time.monotonic()  # eco possível por mais alguns segundos
    flow = runtime.FLOW
    if runtime.GREETING_TURN:
        runtime.GREETING_TURN = False
        context = await runtime.asyncio.to_thread(bridge.context)
        has_previous = len([line for line in context.splitlines() if line.strip()]) > 2
        flow.on_greeting_done(has_previous)
        runtime.log("[VOZ] saudação feita; esperando o Du por 5 s")
        runtime.hud("ouvindo", "Pode falar...")
        return
    action = flow.on_reply_done(spoken)
    if flow.state in {"listening", "ask_resume"}:
        runtime.hud("ouvindo", "Pode responder...")
    elif action == "standby":
        runtime.hud_waiting()


async def flow_ticker(session) -> None:
    """Prazos da conversa: fim do pedido, escuta que acabou, pergunta de continuar."""
    flow = runtime.FLOW
    while runtime.REALTIME and not runtime.SHUTTING_DOWN:
        await runtime.asyncio.sleep(0.2)
        action = flow.tick()
        if action == "respond":
            text = flow.take_collected()
            runtime.log(f"[VOZ] pedido completo: {text[:80]!r}")
            if runtime.is_farewell(text):
                request_shutdown()
            runtime.hud("processando", "Processando comando...")
            await runtime.respond_now(session)
        elif action == "ask_resume":
            runtime.log("[VOZ] silêncio após a saudação; perguntando se continua de onde parou")
            try:
                await session.send_message(
                    "(O Du ficou em silêncio depois da saudação.) Pergunte só, sem mais nada: "
                    "\"Quer que eu continue de onde parei?\""
                )
            except Exception as exc:
                runtime.log(f"[VOZ] pergunta não enviada: {exc}")
        elif action == "standby":
            runtime.log("[VOZ] sem fala; standby")
            runtime.hud_waiting()


async def handle_user_speech(session, item_id: str, text: str) -> None:
    """Aplica as regras de voice/conversation_flow.py a uma fala transcrita."""
    flow = runtime.FLOW
    if busy() and flow.state != "speaking":
        flow.on_speaking()
    short = text if len(text) <= 70 else text[:67] + "..."
    if (addressed(text) or flow.state != "standby") and is_pause_command(text):
        # "Telex, pausa tudo": para tudo e guarda onde parou (core/emergency.py).
        runtime.log(f"[GATE] pausa de emergência: {short!r}")
        await runtime.drop_item(session, item_id)
        await runtime.asyncio.to_thread(
            runtime.post_server, "/api/emergencia", {"acao": "pausar", "origem": "voz"}
        )
        return
    recent = RECENT_SPOKEN if runtime.time.monotonic() - RECENT_SPOKEN_AT < ECHO_SECONDS else ""
    if is_echo(text, (recent + " " + runtime.LAST_ASSISTANT_TEXT).strip()) and not addressed(text):
        runtime.log(f"[GATE] ignore (eco da própria voz): {short!r}")
        await runtime.drop_item(session, item_id)
        return
    state = flow.state
    action = flow.on_transcript(text)
    runtime.log(f"[GATE] {action} (estado {state}): {short!r}")
    if action == "ignore":
        await runtime.drop_item(session, item_id)
        return
    runtime.touch()
    if action in {"interrupt_and_listen", "interrupt_and_collect"}:
        await runtime.interrupt_session()
        runtime.DUQUE_SPEAKING = False
    if action in {"chime", "interrupt_and_listen"}:
        await runtime.drop_item(session, item_id)
        runtime.play_chime()
        runtime.hud("ouvindo", "Pode falar...")
        return
    if action == "sleep":
        await runtime.drop_item(session, item_id)
        runtime.end_session_now("repousar")
        return
    if action == "standby":
        await runtime.drop_item(session, item_id)
        runtime.hud_waiting()
        return
    if action == "resume":
        await runtime.drop_item(session, item_id)
        await runtime.asyncio.to_thread(bridge.record, "user", text, "voz")
        try:
            await session.send_message("Sim, continue de onde paramos.")
        except Exception as exc:
            runtime.log(f"[VOZ] não consegui continuar: {exc}")
        return
    # collect / interrupt_and_collect: guarda e responde quando ele terminar de falar.
    await runtime.asyncio.to_thread(bridge.record, "user", text, "voz")
    runtime.hud("ouvindo", "Escutando você...")


async def receive_events(session) -> None:
    """Consumidor de eventos sem despejar deltas de áudio Base64 no terminal."""
    global RESPONDING, TURN, RECENT_SPOKEN, RECENT_SPOKEN_AT
    runtime.DUQUE_SPEAKING = False
    runtime.SPEECH_STARTED_AT = None
    RESPONDING = False

    async for event in session:
        if not runtime.REALTIME:
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
            runtime.LAST_ASSISTANT_TEXT = speech[1]
            await runtime.asyncio.to_thread(bridge.record, "assistant", speech[1], "voz")

        if kind == "tool_start":
            runtime.touch()
            runtime.hud("executando", "Executando pedido...")
            continue
        if kind == "tool_end":
            runtime.touch()
            runtime.hud("processando", "Resultado recebido")
            continue

        if kind == "raw_model_event":
            server_type = raw_server_type(event)
            if server_type == "input_audio_buffer.speech_started" and not runtime.SHUTTING_DOWN:
                runtime.FLOW.on_speech_started()
                if runtime.FLOW.state in {"listening", "collecting", "ask_resume"}:
                    runtime.hud("ouvindo", "Escutando você...")
            elif server_type == "input_audio_buffer.speech_stopped":
                runtime.FLOW.on_speech_stopped()

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
            runtime.touch()
            if not runtime.DUQUE_SPEAKING:
                runtime.DUQUE_SPEAKING = True
                runtime.FLOW.on_speaking()
                runtime.SPEECH_STARTED_AT = runtime.time.perf_counter()
                runtime.hud("falando", "TELEX falando...")
            runtime.enqueue_audio(
                event.audio.data,
                item_id,
                event.audio.content_index,
                allow_shutdown=allow_shutdown,
            )

        elif kind == "audio_interrupted":
            # Só vem daqui quando NÓS interrompemos (ouviu "Telex"): o modelo do
            # TELEX não se interrompe mais sozinho com som de fundo.
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

        elif kind == "agent_start":
            TURN += 1
            RESPONDING = True
            runtime.FLOW.on_speaking()
            runtime.DUQUE_SPEAKING = False
            runtime.SPEECH_STARTED_AT = None
            runtime.touch()
            if not runtime.SHUTTING_DOWN:
                runtime.hud("processando", "Processando comando...")

        elif kind == "audio_end":
            pass

        elif kind == "agent_end":
            RESPONDING = False
            if runtime.SHUTTING_DOWN:
                await runtime.wait_playback()
                runtime.DUQUE_SPEAKING = False
                if runtime.SHUTDOWN_EVENT:
                    runtime.SHUTDOWN_EVENT.set()
                return
            # Não espera o áudio terminar aqui: o laço precisa continuar lendo
            # eventos para ouvir "Duque, stop" no meio de uma explicação.
            spoken = runtime.LAST_ASSISTANT_TEXT
            runtime.LAST_ASSISTANT_TEXT = ""
            RECENT_SPOKEN, RECENT_SPOKEN_AT = spoken, runtime.time.monotonic() + 30  # vale até tocar tudo
            runtime.asyncio.create_task(finish_turn(TURN, spoken))

        elif kind == "error":
            # Erros do servidor (ex.: resposta já em andamento) não derrubam a
            # conversa; uma queda real da conexão encerra o laço sozinha.
            runtime.log(f"[REALTIME] erro: {getattr(event, 'error', event)}")


patch_identity()
runtime.request_shutdown = request_shutdown
runtime.flow_ticker = flow_ticker
runtime.receive_events = receive_events
runtime.microphone_callback = safe_microphone_callback


if __name__ == "__main__":
    runtime.log(
        f"TELEX Realtime v3 | modelo={runtime.MODEL} | voz={runtime.VOICE} | "
        f"processamento={'on' if runtime.VOICE_PROCESSING else 'off'}"
    )
    runtime.wake_loop()
