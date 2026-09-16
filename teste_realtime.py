import asyncio
import os
import threading
import time
from collections import deque
import urllib.request
import json

import numpy as np
import sounddevice as sd

from pedalboard import (
    Pedalboard,
    Compressor,
    Gain,
    HighpassFilter,
    LowShelfFilter,
    time_stretch,
)

from agents.realtime import (
    OpenAIRealtimeWebSocketModel,
    RealtimeRunner,
    RealtimePlaybackTracker,
)

from agent.duque_realtime import duque_realtime


# ============================================================
# CONFIGURAÇÕES
# ============================================================

MODEL = "gpt-realtime-2.1"

MICROFONE = 1

SAMPLE_RATE = 24000
CANAIS = 1
BLOCKSIZE = 480

VOICE = "cedar"

SERVIDOR = "http://127.0.0.1:5000"


# ============================================================
# VAD LOCAL — INTERRUPÇÃO IMEDIATA
# ============================================================

# Sensibilidade do detector local.
#
# MENOR = mais sensível
# MAIOR = menos sensível
#
# Começamos em 0.045 para tentar detectar sua voz
# sem transformar o eco do Duque em interrupção.
LOCAL_VAD_THRESHOLD = 0.045

# Quantos blocos consecutivos precisam indicar voz.
#
# Cada bloco = 480 samples / 24000 = 20 ms
#
# 3 blocos = aproximadamente 60 ms.
LOCAL_VAD_CONSECUTIVE_BLOCKS = 3

# Tempo mínimo entre duas interrupções locais.
LOCAL_VAD_COOLDOWN = 0.8

# Ignora detecção nos primeiros milissegundos da fala do Duque.
# Isso ajuda a evitar que o primeiro pico do alto-falante
# seja interpretado como sua voz.
LOCAL_VAD_IGNORE_AFTER_SPEECH = 0.25


# ============================================================
# DIAGNÓSTICO
# ============================================================

def horario():

    return (
        time.strftime("%H:%M:%S")
        + f".{int((time.time() % 1) * 1000):03d}"
    )


# ============================================================
# HUD
# ============================================================

def mudar_estado(estado, tarefa=""):

    try:

        dados = json.dumps({
            "estado": estado,
            "tarefa": tarefa
        }).encode("utf-8")

        requisicao = urllib.request.Request(
            f"{SERVIDOR}/api/estado",
            data=dados,
            headers={
                "Content-Type": "application/json"
            },
            method="POST",
        )

        resposta = urllib.request.urlopen(
            requisicao,
            timeout=0.5
        )

        resposta.close()

    except Exception:

        pass


# ============================================================
# PROCESSAMENTO DE VOZ
# ============================================================

PITCH_SEMITONES = -2.0

VELOCIDADE = 0.96

PROCESSING_BUFFER_SAMPLES = 4096


print()
print("Inicializando processamento de voz...")
print()


voz_board = Pedalboard([

    HighpassFilter(
        cutoff_frequency_hz=60.0
    ),

    LowShelfFilter(
        cutoff_frequency_hz=180.0,
        gain_db=3.0
    ),

    Compressor(
        threshold_db=-24.0,
        ratio=2.5,
        attack_ms=10.0,
        release_ms=120.0
    ),

    Gain(
        gain_db=-1.0
    ),

])


print("Processamento de voz inicializado.")

print(
    f"Pitch: {PITCH_SEMITONES:+.1f} semitons"
)

print(
    f"Velocidade: {VELOCIDADE:.2f}x"
)

print("Graves: +3 dB")

print("Compressor: ATIVO")

print()


# ============================================================
# API KEY
# ============================================================

if not os.getenv("OPENAI_API_KEY"):

    print()
    print("ERRO: OPENAI_API_KEY não encontrada.")
    print()

    raise SystemExit(1)


# ============================================================
# MODELO REALTIME
# ============================================================

model = OpenAIRealtimeWebSocketModel(

    transport_config={

        "ping_interval": 20.0,

        "ping_timeout": 60.0,

        "handshake_timeout": 30.0,

        "max_size": 8 * 1024 * 1024,

    }

)


tracker = RealtimePlaybackTracker()


runner = RealtimeRunner(

    starting_agent=duque_realtime,

    model=model,

    config={

        "model_settings": {

            "model_name": MODEL,

            "audio": {

                # =================================================
                # ENTRADA
                # =================================================

                "input": {

                    "format": "pcm16",

                    "noise_reduction": {
                        "type": "far_field"
                    },

                    "transcription": {

                        "model": "gpt-4o-mini-transcribe",

                        "language": "pt",

                    },

                    # =================================================
                    # VAD DO SERVIDOR
                    # =================================================

                    "turn_detection": {

                        "type": "server_vad",

                        "threshold": 0.3,

                        "prefix_padding_ms": 300,

                        "silence_duration_ms": 250,

                        "interrupt_response": True,

                        "create_response": True,

                    },

                },

                # =================================================
                # SAÍDA
                # =================================================

                "output": {

                    "format": "pcm16",

                    "voice": VOICE,

                },

            },

        },

        "tracing_disabled": True,

    },

)


# ============================================================
# ESTADO GLOBAL
# ============================================================

LOOP = None

SESSION = None


fila_microfone = asyncio.Queue(
    maxsize=100
)


audio_buffer = deque()

audio_lock = threading.Lock()


audio_interrompido = False

duque_falando = False


item_audio_atual = None

itens_cancelados = set()

itens_lock = threading.Lock()


processamento_buffer = bytearray()

processamento_item_id = None

processamento_content_index = None

processamento_lock = threading.Lock()


# ============================================================
# ESTADO DO VAD LOCAL
# ============================================================

local_vad_consecutivos = 0

local_vad_ultima_interrupcao = 0.0

inicio_fala_duque = None

local_vad_interrompendo = False


# ============================================================
# FUNÇÃO DE RMS
# ============================================================

def calcular_rms(audio):

    try:

        samples = np.frombuffer(
            audio,
            dtype=np.int16
        ).astype(np.float32)

        if len(samples) == 0:

            return 0.0

        samples /= 32768.0

        rms = np.sqrt(
            np.mean(
                samples * samples
            )
        )

        return float(rms)

    except Exception:

        return 0.0


# ============================================================
# INTERRUPÇÃO LOCAL
# ============================================================

def solicitar_interrupcao_local():

    global local_vad_interrompendo

    global local_vad_ultima_interrupcao


    if LOOP is None:
        return


    if SESSION is None:
        return


    agora = time.perf_counter()


    if (
        agora - local_vad_ultima_interrupcao
        < LOCAL_VAD_COOLDOWN
    ):

        return


    if local_vad_interrompendo:

        return


    local_vad_interrompendo = True

    local_vad_ultima_interrupcao = agora


    print()

    print(
        f"[{horario()}] "
        ">>> VAD LOCAL: VOZ DETECTADA <<<"
    )

    print()

    print(
        f"[{horario()}] "
        ">>> INTERRUPÇÃO LOCAL IMEDIATA <<<"
    )

    print()


    # --------------------------------------------------------
    # PRIMEIRO: corta nosso áudio local imediatamente.
    # --------------------------------------------------------

    limpar_audio()

    resetar_processamento_voz()


    # --------------------------------------------------------
    # SEGUNDO: pede ao Realtime para interromper a resposta.
    #
    # session.interrupt() é assíncrono.
    # --------------------------------------------------------

    async def executar_interrupcao():

        global local_vad_interrompendo

        try:

            await SESSION.interrupt()

        except Exception as erro:

            print()

            print(
                f"[VAD LOCAL] "
                f"Erro ao interromper sessão: {erro}"
            )

            print()

        finally:

            local_vad_interrompendo = False


    try:

        LOOP.call_soon_threadsafe(

            lambda: asyncio.create_task(
                executar_interrupcao()
            )

        )

    except Exception as erro:

        local_vad_interrompendo = False

        print(
            f"[VAD LOCAL] "
            f"Erro ao agendar interrupção: {erro}"
        )


# ============================================================
# VAD LOCAL
# ============================================================

def processar_vad_local(audio):

    global local_vad_consecutivos

    global inicio_fala_duque


    # Só interessa quando o Duque está falando.

    if not duque_falando:

        local_vad_consecutivos = 0

        return


    # --------------------------------------------------------
    # Evita pegar o primeiro impacto do próprio alto-falante.
    # --------------------------------------------------------

    if inicio_fala_duque is not None:

        tempo_falando = (
            time.perf_counter()
            - inicio_fala_duque
        )

        if (
            tempo_falando
            < LOCAL_VAD_IGNORE_AFTER_SPEECH
        ):

            local_vad_consecutivos = 0

            return


    rms = calcular_rms(
        audio
    )


    # Debug leve.
    #
    # Não imprime cada bloco porque seriam 50 mensagens
    # por segundo.
    #
    # Só contabilizamos internamente.

    if rms >= LOCAL_VAD_THRESHOLD:

        local_vad_consecutivos += 1

    else:

        local_vad_consecutivos = 0


    # --------------------------------------------------------
    # Voz sustentada por aproximadamente 60 ms.
    # --------------------------------------------------------

    if (
        local_vad_consecutivos
        >= LOCAL_VAD_CONSECUTIVE_BLOCKS
    ):

        local_vad_consecutivos = 0

        solicitar_interrupcao_local()


# ============================================================
# CALLBACK DO MICROFONE
# ============================================================

def callback_microfone(
    indata,
    frames,
    time_info,
    status
):

    if status:

        print(
            f"\n[MIC] {status}"
        )


    audio = (
        indata.copy().tobytes()
    )


    # --------------------------------------------------------
    # VAD LOCAL RODA IMEDIATAMENTE NO BLOCO DO MICROFONE.
    # --------------------------------------------------------

    processar_vad_local(
        audio
    )


    if LOOP is None:

        return


    try:

        LOOP.call_soon_threadsafe(
            adicionar_audio_microfone,
            audio
        )

    except Exception:

        pass


# ============================================================
# FILA DO MICROFONE
# ============================================================

def adicionar_audio_microfone(
    audio
):

    try:

        fila_microfone.put_nowait(
            audio
        )

    except asyncio.QueueFull:

        pass


# ============================================================
# ENVIO DO MICROFONE
# ============================================================

async def enviar_microfone(
    session
):

    print(
        "[MIC] Microfone ativo."
    )

    while True:

        audio = (
            await fila_microfone.get()
        )

        await session.send_audio(
            audio
        )


# ============================================================
# ITENS CANCELADOS
# ============================================================

def item_foi_cancelado(
    item_id
):

    if item_id is None:

        return False


    with itens_lock:

        return (
            item_id
            in itens_cancelados
        )


def cancelar_item_atual():

    global item_audio_atual


    with itens_lock:

        if item_audio_atual is not None:

            itens_cancelados.add(
                item_audio_atual
            )

            print(
                f"[{horario()}] "
                f"[ÁUDIO] Item cancelado: "
                f"{item_audio_atual}"
            )


        item_audio_atual = None


# ============================================================
# PROCESSAMENTO DE ÁUDIO
# ============================================================

def processar_bloco_audio(
    data
):

    try:

        audio = np.frombuffer(
            data,
            dtype=np.int16
        ).astype(np.float32)


        audio /= 32768.0


        audio = audio.reshape(
            1,
            -1
        )


        audio = voz_board.process(

            audio,

            SAMPLE_RATE,

            buffer_size=2048,

            reset=False,

        )


        audio = time_stretch(

            audio,

            SAMPLE_RATE,

            stretch_factor=VELOCIDADE,

            pitch_shift_in_semitones=PITCH_SEMITONES,

            high_quality=True,

            transient_mode="crisp",

            transient_detector="compound",

            retain_phase_continuity=True,

            preserve_formants=True,

        )


        audio = np.clip(
            audio,
            -1.0,
            1.0
        )


        audio = (
            audio * 32767.0
        ).astype(np.int16)


        return audio.tobytes()


    except Exception as erro:

        print()

        print(
            f"[VOZ] Erro no processamento: {erro}"
        )

        print()

        print(
            "[VOZ] Usando áudio original."
        )

        print()

        return data


# ============================================================
# ADICIONAR ÁUDIO PROCESSADO
# ============================================================

def adicionar_audio_processado(
    data,
    item_id,
    content_index
):

    global audio_interrompido


    if item_foi_cancelado(
        item_id
    ):

        return


    with audio_lock:

        if audio_interrompido:

            return


        audio_buffer.append(

            (
                item_id,
                content_index,
                data
            )

        )


# ============================================================
# PROCESSAR BUFFER
# ============================================================

def processar_buffer_se_necessario():

    global processamento_buffer

    global processamento_item_id

    global processamento_content_index


    while True:

        with processamento_lock:

            bytes_por_sample = 2

            bytes_necessarios = (
                PROCESSING_BUFFER_SAMPLES
                * bytes_por_sample
            )


            if (
                len(processamento_buffer)
                < bytes_necessarios
            ):

                return


            bloco = bytes(
                processamento_buffer[
                    :bytes_necessarios
                ]
            )


            del processamento_buffer[
                :bytes_necessarios
            ]


            item_id = (
                processamento_item_id
            )


            content_index = (
                processamento_content_index
            )


        if item_foi_cancelado(
            item_id
        ):

            continue


        resultado = (
            processar_bloco_audio(
                bloco
            )
        )


        if not resultado:

            resultado = bloco


        adicionar_audio_processado(

            resultado,

            item_id,

            content_index

        )


# ============================================================
# ADICIONAR ÁUDIO DE SAÍDA
# ============================================================

def adicionar_audio_saida(

    data,

    item_id,

    content_index

):

    global processamento_item_id

    global processamento_content_index

    global audio_interrompido

    global item_audio_atual


    if item_foi_cancelado(
        item_id
    ):

        return


    with itens_lock:

        item_audio_atual = item_id


    with audio_lock:

        if audio_interrompido:

            return


    with processamento_lock:

        if processamento_item_id is None:

            processamento_item_id = (
                item_id
            )


        if processamento_content_index is None:

            processamento_content_index = (
                content_index
            )


        processamento_buffer.extend(
            data
        )


    processar_buffer_se_necessario()


# ============================================================
# FINALIZAR BUFFER
# ============================================================

def finalizar_buffer_audio():

    global processamento_buffer

    global processamento_item_id

    global processamento_content_index


    with processamento_lock:

        if not processamento_buffer:

            processamento_item_id = None

            processamento_content_index = None

            return


        bloco = bytes(
            processamento_buffer
        )


        item_id = (
            processamento_item_id
        )


        content_index = (
            processamento_content_index
        )


        processamento_buffer.clear()

        processamento_item_id = None

        processamento_content_index = None


    if item_foi_cancelado(
        item_id
    ):

        return


    resultado = (
        processar_bloco_audio(
            bloco
        )
    )


    if not resultado:

        resultado = bloco


    adicionar_audio_processado(

        resultado,

        item_id,

        content_index

    )


# ============================================================
# LIMPAR ÁUDIO
# ============================================================

def limpar_audio():

    global processamento_item_id

    global processamento_content_index


    with audio_lock:

        audio_buffer.clear()


    with processamento_lock:

        processamento_buffer.clear()

        processamento_item_id = None

        processamento_content_index = None


# ============================================================
# RESETAR PROCESSADOR
# ============================================================

def resetar_processamento_voz():

    try:

        voz_board.reset()

        print(
            f"[{horario()}] "
            "[VOZ] Processador reiniciado."
        )

    except Exception as erro:

        print(
            f"[VOZ] Erro ao reiniciar processador: {erro}"
        )


# ============================================================
# CALLBACK DO PLAYER
# ============================================================

def callback_saida(

    outdata,

    frames,

    time_info,

    status

):

    if status:

        print(
            f"\n[PLAYER] {status}"
        )


    bytes_necessarios = (
        frames
        * 2
        * CANAIS
    )


    resultado = bytearray()

    blocos_reproduzidos = []


    with audio_lock:

        while (

            len(resultado)
            < bytes_necessarios

            and audio_buffer

        ):

            item_id, content_index, data = (
                audio_buffer[0]
            )


            if item_foi_cancelado(
                item_id
            ):

                audio_buffer.popleft()

                continue


            faltam = (
                bytes_necessarios
                - len(resultado)
            )


            if len(data) <= faltam:

                resultado.extend(
                    data
                )

                audio_buffer.popleft()


                blocos_reproduzidos.append(

                    (
                        item_id,
                        content_index,
                        data
                    )

                )

            else:

                parte = data[
                    :faltam
                ]


                restante = data[
                    faltam:
                ]


                resultado.extend(
                    parte
                )


                audio_buffer[0] = (

                    item_id,

                    content_index,

                    restante

                )


                blocos_reproduzidos.append(

                    (
                        item_id,
                        content_index,
                        parte
                    )

                )


        if (
            len(resultado)
            < bytes_necessarios
        ):

            resultado.extend(

                b"\x00"
                * (
                    bytes_necessarios
                    - len(resultado)
                )

            )


    outdata[:] = bytes(
        resultado
    )


    for (

        item_id,

        content_index,

        data

    ) in blocos_reproduzidos:

        try:

            tracker.on_play_bytes(

                item_id,

                content_index,

                data

            )

        except Exception:

            pass


# ============================================================
# AGUARDAR PLAYBACK
# ============================================================

async def aguardar_fim_playback():

    global duque_falando

    global inicio_fala_duque


    await asyncio.sleep(
        0.10
    )


    while True:

        with audio_lock:

            ainda_tem_audio = (
                len(audio_buffer)
                > 0
            )


        with processamento_lock:

            ainda_processando = (
                len(processamento_buffer)
                > 0
            )


        if (

            not ainda_tem_audio

            and not ainda_processando

        ):

            break


        await asyncio.sleep(
            0.05
        )


    duque_falando = False

    inicio_fala_duque = None


    print()

    print(
        f"[{horario()}] "
        ">>> PLAYBACK TERMINOU <<<"
    )

    print()


    mudar_estado(
        "standby",
        "Sistema online"
    )


# ============================================================
# EVENTOS REALTIME
# ============================================================

async def receber_eventos(
    session
):

    global audio_interrompido

    global duque_falando

    global item_audio_atual

    global inicio_fala_duque


    async for event in session:

        tipo = getattr(
            event,
            "type",
            ""
        )


        # ====================================================
        # RAW MODEL EVENT
        # ====================================================

        if tipo == "raw_model_event":

            try:

                dados = getattr(
                    event,
                    "data",
                    None
                )


                tipo_raw = getattr(
                    dados,
                    "type",
                    ""
                )


                if not tipo_raw:

                    continue


                if (
                    tipo_raw
                    == "input_audio_buffer.speech_started"
                ):

                    print()

                    print(
                        f"[{horario()}] "
                        ">>> SERVER: SPEECH STARTED <<<"
                    )

                    print()


                    mudar_estado(

                        "ouvindo",

                        "Escutando você..."

                    )


                elif (
                    tipo_raw
                    == "input_audio_buffer.speech_stopped"
                ):

                    print()

                    print(
                        f"[{horario()}] "
                        ">>> SERVER: SPEECH STOPPED <<<"
                    )

                    print()


                elif any(

                    palavra in tipo_raw

                    for palavra in (

                        "turn",

                        "response",

                    )

                ):

                    print(

                        f"[{horario()}] "
                        f"[RAW] {tipo_raw}"

                    )


            except Exception as erro:

                print(
                    f"[RAW] Erro: {erro}"
                )


        # ====================================================
        # ÁUDIO
        # ====================================================

        elif tipo == "audio":

            try:

                item_id = (
                    event.audio.item_id
                )


                content_index = (
                    event.audio.content_index
                )


                data = (
                    event.audio.data
                )


                if item_foi_cancelado(
                    item_id
                ):

                    continue


                audio_interrompido = False


                with itens_lock:

                    item_audio_atual = (
                        item_id
                    )


                if not duque_falando:

                    duque_falando = True

                    inicio_fala_duque = (
                        time.perf_counter()
                    )


                    print()

                    print(
                        f"[{horario()}] "
                        ">>> DUQUE: FALANDO <<<"
                    )

                    print()


                    mudar_estado(

                        "falando",

                        "Duque falando..."

                    )


                adicionar_audio_saida(

                    data,

                    item_id,

                    content_index

                )


            except Exception as erro:

                print()

                print(
                    f"[ÁUDIO] Erro: {erro}"
                )

                print()


        # ====================================================
        # ÁUDIO INTERROMPIDO
        # ====================================================

        elif tipo == "audio_interrupted":

            print()

            print(
                f"[{horario()}] "
                ">>> ÁUDIO INTERROMPIDO <<<"
            )

            print()


            cancelar_item_atual()


            audio_interrompido = True


            limpar_audio()


            resetar_processamento_voz()


            duque_falando = False

            inicio_fala_duque = None


            mudar_estado(

                "ouvindo",

                "Escutando você..."

            )


            try:

                tracker.on_interrupted()

            except Exception:

                pass


        # ====================================================
        # AGENTE COMEÇOU
        # ====================================================

        elif tipo == "agent_start":

            audio_interrompido = False

            duque_falando = False

            inicio_fala_duque = None


            print()

            print(
                f"[{horario()}] "
                ">>> DUQUE: PROCESSANDO <<<"
            )

            print()


            mudar_estado(

                "processando",

                "Processando comando..."

            )


        # ====================================================
        # ÁUDIO TERMINOU
        # ====================================================

        elif tipo == "audio_end":

            print()

            print(
                f"[{horario()}] "
                ">>> ÁUDIO DO DUQUE TERMINOU <<<"
            )

            print()


            finalizar_buffer_audio()


        # ====================================================
        # AGENTE TERMINOU
        # ====================================================

        elif tipo == "agent_end":

            finalizar_buffer_audio()


            print()

            print(
                f"[{horario()}] "
                ">>> DUQUE TERMINOU DE GERAR <<<"
            )

            print()


            asyncio.create_task(

                aguardar_fim_playback()

            )


        # ====================================================
        # HISTÓRICO
        # ====================================================

        elif tipo == "history_added":

            print(

                f"[{horario()}] "
                "[EVENTO] history_added"

            )


        # ====================================================
        # ERRO
        # ====================================================

        elif tipo == "error":

            print()

            print(
                "=" * 60
            )

            print(
                "ERRO DO REALTIME"
            )

            print(
                "=" * 60
            )

            print()

            print(
                getattr(
                    event,
                    "error",
                    event
                )
            )

            print()


            duque_falando = False

            inicio_fala_duque = None

            audio_interrompido = False


            mudar_estado(

                "standby",

                "Sistema online"

            )


# ============================================================
# MAIN
# ============================================================

async def main():

    global LOOP

    global SESSION


    LOOP = (
        asyncio.get_running_loop()
    )


    mudar_estado(

        "standby",

        "Sistema online"

    )


    print()

    print(
        "=" * 60
    )

    print(
        "DUQUE REALTIME"
    )

    print(
        "=" * 60
    )

    print()


    print(
        f"Modelo: {MODEL}"
    )

    print(
        f"Microfone: {MICROFONE}"
    )

    print(
        f"Voz base: {VOICE}"
    )

    print()


    print(
        "Agente: duque_realtime"
    )

    print(
        "VAD servidor: server_vad"
    )

    print(
        "Threshold servidor: 0.30"
    )

    print()


    print(
        ">>> VAD LOCAL: ATIVO <<<"
    )

    print(
        f"Threshold local: {LOCAL_VAD_THRESHOLD}"
    )

    print(
        f"Blocos consecutivos: "
        f"{LOCAL_VAD_CONSECUTIVE_BLOCKS}"
    )

    print(
        "Interrupção local: ATIVA"
    )

    print()


    print(
        "Microfone durante fala: ATIVO"
    )

    print(
        "Cancelamento de áudio antigo: ATIVO"
    )

    print(
        "Playback tracker: ATIVO"
    )

    print(
        "Processamento de voz: ATIVO"
    )

    print(
        f"Pitch: {PITCH_SEMITONES:+.1f} semitons"
    )

    print(
        f"Velocidade: {VELOCIDADE:.2f}x"
    )

    print(
        "Graves: +3 dB"
    )

    print(
        f"Buffer: {PROCESSING_BUFFER_SAMPLES} samples"
    )

    print()


    # ========================================================
    # PLAYER
    # ========================================================

    print(
        "Iniciando saída de áudio..."
    )


    player = sd.RawOutputStream(

        samplerate=SAMPLE_RATE,

        channels=CANAIS,

        dtype="int16",

        blocksize=BLOCKSIZE,

        callback=callback_saida,

    )


    player.start()


    print(
        "Saída de áudio iniciada."
    )

    print()


    # ========================================================
    # CONEXÃO
    # ========================================================

    print(
        "Conectando ao Realtime..."
    )

    print()


    session = await runner.run(

        model_config={

            "playback_tracker": tracker

        }

    )


    async with session:

        SESSION = session


        print(
            "=" * 60
        )

        print(
            "DUQUE CONECTADO"
        )

        print(
            "=" * 60
        )

        print()


        print(
            "Pode falar."
        )

        print()


        mudar_estado(

            "standby",

            "Sistema online"

        )


        with sd.InputStream(

            samplerate=SAMPLE_RATE,

            channels=CANAIS,

            dtype=np.int16,

            device=MICROFONE,

            blocksize=BLOCKSIZE,

            callback=callback_microfone,

        ):

            await asyncio.gather(

                enviar_microfone(
                    session
                ),

                receber_eventos(
                    session
                ),

            )


# ============================================================
# EXECUÇÃO
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )


    except KeyboardInterrupt:

        print()

        print()

        print(
            "Duque encerrado."
        )


        mudar_estado(

            "standby",

            "Sistema offline"

        )


    except Exception as erro:

        print()

        print()

        print(
            "=" * 60
        )

        print(
            "ERRO"
        )

        print(
            "=" * 60
        )

        print()

        print(
            repr(erro)
        )

        print()


        mudar_estado(

            "standby",

            "Erro no sistema"

        )