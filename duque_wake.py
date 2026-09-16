import asyncio
import json
import os
import threading
import time
import urllib.request
from collections import deque

import numpy as np
import sounddevice as sd

from openwakeword.model import Model
from pvrecorder import PvRecorder

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
# CONFIGURAÇÕES GERAIS
# ============================================================

MODEL = "gpt-realtime-2.1"

MICROFONE = 1

SAMPLE_RATE = 24000
CANAIS = 1
BLOCKSIZE = 480

VOICE = "cedar"

SERVIDOR = "http://127.0.0.1:5000"


# ============================================================
# CONFIGURAÇÕES DO WAKE WORD
# ============================================================

WAKEWORD = "hey_jarvis"

FRAME_LENGTH = 1280

LIMIAR = 0.5

COOLDOWN = 2.0


# ============================================================
# CONFIGURAÇÕES DE ENCERRAMENTO
# ============================================================

FRASES_ENCERRAMENTO = [

    "até mais duque",
    "até mais, duque",

    "até logo duque",
    "até logo, duque",

    "tchau duque",
    "tchau, duque",

    "pode dormir duque",
    "pode dormir, duque",

]


# ============================================================
# VAD LOCAL — INTERRUPÇÃO IMEDIATA
# ============================================================

LOCAL_VAD_THRESHOLD = 0.045

LOCAL_VAD_CONSECUTIVE_BLOCKS = 3

LOCAL_VAD_COOLDOWN = 0.8

LOCAL_VAD_IGNORE_AFTER_SPEECH = 0.25


# ============================================================
# PROCESSAMENTO DE VOZ
# ============================================================

PITCH_SEMITONES = -2.0

VELOCIDADE = 0.96

PROCESSING_BUFFER_SAMPLES = 4096


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

def mudar_estado(
    estado,
    tarefa=""
):

    try:

        dados = json.dumps({

            "estado": estado,

            "tarefa": tarefa

        }).encode("utf-8")


        requisicao = urllib.request.Request(

            f"{SERVIDOR}/api/estado",

            data=dados,

            headers={

                "Content-Type":
                "application/json"

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

    print(
        "ERRO: OPENAI_API_KEY não encontrada."
    )

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

                        "model":
                        "gpt-4o-mini-transcribe",

                        "language": "pt",

                    },

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
# ESTADO GLOBAL DO REALTIME
# ============================================================

LOOP = None

SESSION = None

REALTIME_ATIVO = False

ENCERRAR_REALTIME = False

MICROFONE_ATIVO = False

encerramento_evento = None


# ============================================================
# PLAYBACK TRACKER GLOBAL
# ============================================================

tracker = None


# ============================================================
# FILA DO MICROFONE
#
# IMPORTANTE:
# Esta fila NÃO pode ser criada aqui.
#
# Cada asyncio.run() cria um Event Loop novo.
# A fila agora será criada dentro de executar_realtime().
# ============================================================

fila_microfone = None


# ============================================================
# PLAYBACK
# ============================================================

audio_buffer = deque()

audio_lock = threading.Lock()

audio_interrompido = False

duque_falando = False

item_audio_atual = None

itens_cancelados = set()

itens_lock = threading.Lock()


# ============================================================
# PROCESSAMENTO
# ============================================================

processamento_buffer = bytearray()

processamento_item_id = None

processamento_content_index = None

processamento_lock = threading.Lock()


# ============================================================
# VAD LOCAL
# ============================================================

local_vad_consecutivos = 0

local_vad_ultima_interrupcao = 0.0

inicio_fala_duque = None

local_vad_interrompendo = False


# ============================================================
# TEXTO / ENCERRAMENTO
# ============================================================

ultimo_texto_reconhecido = ""

texto_lock = threading.Lock()


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
# DETECTAR FRASE DE ENCERRAMENTO
# ============================================================

def verificar_frase_encerramento(
    texto
):

    if not texto:

        return False


    texto = texto.lower().strip()


    for frase in FRASES_ENCERRAMENTO:

        if frase in texto:

            return True


    return False


# ============================================================
# EXTRAIR TEXTO
# ============================================================

def extrair_texto_objeto(
    objeto,
    profundidade=0
):

    if objeto is None:

        return ""


    if profundidade > 6:

        return ""


    partes = []


    if isinstance(
        objeto,
        str
    ):

        return objeto


    if isinstance(
        objeto,
        dict
    ):

        for chave, valor in objeto.items():

            chave_lower = str(
                chave
            ).lower()


            if chave_lower in (

                "text",
                "transcript",
                "transcription",
                "delta",

            ):

                if isinstance(
                    valor,
                    str
                ):

                    partes.append(
                        valor
                    )

                else:

                    texto = (
                        extrair_texto_objeto(
                            valor,
                            profundidade + 1
                        )
                    )

                    if texto:

                        partes.append(
                            texto
                        )


            else:

                texto = (
                    extrair_texto_objeto(
                        valor,
                        profundidade + 1
                    )
                )

                if texto:

                    partes.append(
                        texto
                    )


        return " ".join(partes)


    if isinstance(
        objeto,
        (
            list,
            tuple,
            set
        )
    ):

        for item in objeto:

            texto = (
                extrair_texto_objeto(
                    item,
                    profundidade + 1
                )
            )

            if texto:

                partes.append(
                    texto
                )


        return " ".join(partes)


    atributos = (

        "text",

        "transcript",

        "transcription",

        "delta",

        "item",

        "content",

        "parts",

        "data",

    )


    for atributo in atributos:

        try:

            valor = getattr(
                objeto,
                atributo,
                None
            )

        except Exception:

            valor = None


        if valor is None:

            continue


        if isinstance(
            valor,
            str
        ):

            partes.append(
                valor
            )

        else:

            texto = (
                extrair_texto_objeto(
                    valor,
                    profundidade + 1
                )
            )

            if texto:

                partes.append(
                    texto
                )


    return " ".join(partes)


# ============================================================
# SOLICITAR ENCERRAMENTO
# ============================================================

def solicitar_encerramento():

    global ENCERRAR_REALTIME
    global MICROFONE_ATIVO


    if ENCERRAR_REALTIME:

        return


    ENCERRAR_REALTIME = True

    # --------------------------------------------------------
    # IMPORTANTE:
    # Assim que a frase de encerramento é detectada,
    # paramos imediatamente de aceitar novos áudios do usuário.
    #
    # A sessão continua viva apenas para terminar a despedida.
    # --------------------------------------------------------

    MICROFONE_ATIVO = False

    limpar_fila_microfone()


    print()

    print(
        f"[{horario()}] "
        ">>> ENCERRAMENTO SOLICITADO <<<"
    )

    print()

    print(
        "Microfone desativado."
    )

    print()

    print(
        "Aguardando Duque terminar a despedida..."
    )

    print()


    mudar_estado(

        "processando",

        "Encerrando conversa..."

    )


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


    if not REALTIME_ATIVO:

        return


    if ENCERRAR_REALTIME:

        return


    if not MICROFONE_ATIVO:

        return


    agora = time.perf_counter()


    if (

        agora
        - local_vad_ultima_interrupcao

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


    limpar_audio()

    resetar_processamento_voz()


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

def processar_vad_local(
    audio
):

    global local_vad_consecutivos

    global inicio_fala_duque


    if not MICROFONE_ATIVO:

        local_vad_consecutivos = 0

        return


    if not duque_falando:

        local_vad_consecutivos = 0

        return


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


    if rms >= LOCAL_VAD_THRESHOLD:

        local_vad_consecutivos += 1

    else:

        local_vad_consecutivos = 0


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


    # --------------------------------------------------------
    # Se o microfone foi desativado pelo encerramento,
    # simplesmente ignoramos o callback.
    # --------------------------------------------------------

    if not REALTIME_ATIVO:

        return


    if not MICROFONE_ATIVO:

        return


    audio = (
        indata.copy().tobytes()
    )


    # --------------------------------------------------------
    # VAD LOCAL IMEDIATO
    # --------------------------------------------------------

    processar_vad_local(
        audio
    )


    # --------------------------------------------------------
    # ENVIO PARA O LOOP ASYNC
    # --------------------------------------------------------

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
# ADICIONAR ÁUDIO DO MICROFONE
# ============================================================

def adicionar_audio_microfone(
    audio
):

    if not REALTIME_ATIVO:

        return


    if not MICROFONE_ATIVO:

        return


    if fila_microfone is None:

        return


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
        "[MIC] Microfone Realtime ativo."
    )


    while REALTIME_ATIVO:

        try:

            audio = await asyncio.wait_for(

                fila_microfone.get(),

                timeout=0.1

            )

        except asyncio.TimeoutError:

            continue


        if not REALTIME_ATIVO:

            break


        if not MICROFONE_ATIVO:

            continue


        try:

            await session.send_audio(
                audio
            )

        except Exception as erro:

            print()

            print(
                f"[MIC] Erro enviando áudio: {erro}"
            )

            print()

            break


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
# PROCESSAR BLOCO DE ÁUDIO
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

            processamento_item_id = item_id


        if processamento_content_index is None:

            processamento_content_index = (
                content_index
            )


        processamento_buffer.extend(
            data
        )


    processar_buffer_se_necessario()


# ============================================================
# FINALIZAR BUFFER DE ÁUDIO
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

            f"[VOZ] Erro ao reiniciar processador: "
            f"{erro}"

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


    if tracker is not None:

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


    while REALTIME_ATIVO:

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


    if not REALTIME_ATIVO:

        return


    duque_falando = False

    inicio_fala_duque = None


    print()

    print(

        f"[{horario()}] "
        ">>> PLAYBACK TERMINOU <<<"

    )

    print()


    if not ENCERRAR_REALTIME:

        mudar_estado(

            "ouvindo",

            "Escutando você..."

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

    global ultimo_texto_reconhecido

    global encerramento_evento


    async for event in session:

        if not REALTIME_ATIVO:

            break


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


                    # ------------------------------------------------
                    # DURANTE O ENCERRAMENTO, NÃO VOLTAMOS PARA
                    # "OUVINDO".
                    # ------------------------------------------------

                    if not ENCERRAR_REALTIME:

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


                texto_evento = (
                    extrair_texto_objeto(
                        dados
                    )
                )


                if texto_evento:

                    texto_evento = (
                        texto_evento.strip()
                    )


                    if texto_evento:

                        with texto_lock:

                            ultimo_texto_reconhecido = (
                                texto_evento
                            )


                        print(

                            f"[{horario()}] "
                            f"[TRANSCRIÇÃO] "
                            f"{texto_evento}"

                        )


                        if verificar_frase_encerramento(

                            texto_evento

                        ):

                            solicitar_encerramento()


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


            if not ENCERRAR_REALTIME:

                mudar_estado(

                    "ouvindo",

                    "Escutando você..."

                )


            if tracker is not None:

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


            if not ENCERRAR_REALTIME:

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


            # ------------------------------------------------
            # ENCERRAMENTO SOLICITADO
            # ------------------------------------------------

            if ENCERRAR_REALTIME:

                print()

                print(

                    f"[{horario()}] "
                    ">>> AGUARDANDO FIM DA DESPEDIDA <<<"

                )

                print()


                await aguardar_fim_playback()


                print()

                print(

                    f"[{horario()}] "
                    ">>> DESPEDIDA FINALIZADA <<<"

                )

                print()


                # ------------------------------------------------
                # SINALIZA PARA executar_realtime()
                # QUE A SESSÃO PODE SER ENCERRADA.
                # ------------------------------------------------

                if encerramento_evento is not None:

                    encerramento_evento.set()


                return


            # ------------------------------------------------
            # CONVERSA NORMAL
            # ------------------------------------------------

            asyncio.create_task(

                aguardar_fim_playback()

            )


        # ====================================================
        # HISTÓRICO
        # ====================================================

        elif tipo == "history_added":

            try:

                texto = (
                    extrair_texto_objeto(
                        event
                    )
                )


                if texto:

                    texto = texto.strip()


                    if texto:

                        with texto_lock:

                            ultimo_texto_reconhecido = (
                                texto
                            )


                        print(

                            f"[{horario()}] "
                            f"[HISTÓRICO] "
                            f"{texto}"

                        )


                        if verificar_frase_encerramento(
                            texto
                        ):

                            solicitar_encerramento()


            except Exception as erro:

                print(

                    f"[HISTÓRICO] Erro: {erro}"

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


            break


# ============================================================
# LIMPAR FILA DO MICROFONE
# ============================================================

def limpar_fila_microfone():

    global fila_microfone


    if fila_microfone is None:

        return


    while True:

        try:

            fila_microfone.get_nowait()

        except asyncio.QueueEmpty:

            break


# ============================================================
# EXECUTAR UMA SESSÃO REALTIME
# ============================================================

async def executar_realtime():

    global LOOP

    global SESSION

    global REALTIME_ATIVO

    global ENCERRAR_REALTIME

    global MICROFONE_ATIVO

    global encerramento_evento

    global audio_interrompido

    global duque_falando

    global inicio_fala_duque

    global item_audio_atual

    global itens_cancelados

    global processamento_buffer

    global processamento_item_id

    global processamento_content_index

    global local_vad_consecutivos

    global local_vad_ultima_interrupcao

    global local_vad_interrompendo

    global ultimo_texto_reconhecido

    global tracker

    global fila_microfone


    # ========================================================
    # PEGAR EVENT LOOP ATUAL
    # ========================================================

    LOOP = asyncio.get_running_loop()


    # ========================================================
    # CRIAR NOVA FILA PARA ESTE EVENT LOOP
    # ========================================================

    fila_microfone = asyncio.Queue(
        maxsize=100
    )


    # ========================================================
    # EVENTO DE ENCERRAMENTO
    #
    # Também é criado por sessão para nunca carregar estado
    # de uma execução anterior.
    # ========================================================

    encerramento_evento = asyncio.Event()


    # ========================================================
    # RESET COMPLETO DA SESSÃO
    # ========================================================

    REALTIME_ATIVO = True

    ENCERRAR_REALTIME = False

    MICROFONE_ATIVO = False


    SESSION = None

    tracker = None


    audio_interrompido = False

    duque_falando = False

    inicio_fala_duque = None


    item_audio_atual = None


    with itens_lock:

        itens_cancelados.clear()


    with audio_lock:

        audio_buffer.clear()


    with processamento_lock:

        processamento_buffer.clear()

        processamento_item_id = None

        processamento_content_index = None


    local_vad_consecutivos = 0

    local_vad_ultima_interrupcao = 0.0

    local_vad_interrompendo = False


    with texto_lock:

        ultimo_texto_reconhecido = ""


    resetar_processamento_voz()


    # ========================================================
    # HUD
    # ========================================================

    mudar_estado(

        "ouvindo",

        "Escutando você..."

    )


    print()

    print(
        "=" * 60
    )

    print(
        "DUQUE REALTIME ATIVADO"
    )

    print(
        "=" * 60
    )

    print()

    print(
        "Realtime assumiu o microfone."
    )

    print(
        "Diga seu comando."
    )

    print()

    print(
        'Para encerrar: "até mais, Duque".'
    )

    print()


    player = None

    input_stream = None


    try:

        # ====================================================
        # PLAYER
        # ====================================================

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


        # ====================================================
        # CONEXÃO
        # ====================================================

        print(
            "Conectando ao Realtime..."
        )

        print()


        tracker = RealtimePlaybackTracker()


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


            # =================================================
            # MICROFONE
            # =================================================

            input_stream = sd.InputStream(

                samplerate=SAMPLE_RATE,

                channels=CANAIS,

                dtype=np.int16,

                device=MICROFONE,

                blocksize=BLOCKSIZE,

                callback=callback_microfone,

            )


            input_stream.start()


            MICROFONE_ATIVO = True


            print(
                "Microfone Realtime ativo."
            )

            print()


            # =================================================
            # TAREFAS DO REALTIME
            # =================================================

            tarefa_microfone = asyncio.create_task(

                enviar_microfone(
                    session
                )

            )


            tarefa_eventos = asyncio.create_task(

                receber_eventos(
                    session
                )

            )


            try:

                # ------------------------------------------------
                # A conversa normal termina quando uma tarefa
                # realmente termina.
                #
                # No encerramento:
                # receber_eventos() aguarda a despedida,
                # sinaliza encerramento_evento e termina.
                # ------------------------------------------------

                tarefa_aguardar_encerramento = asyncio.create_task(

                    encerramento_evento.wait()

                )


                concluida, pendente = await asyncio.wait(

                    [

                        tarefa_microfone,

                        tarefa_eventos,

                        tarefa_aguardar_encerramento

                    ],

                    return_when=asyncio.FIRST_COMPLETED

                )


                for tarefa in concluida:

                    try:

                        tarefa.result()

                    except asyncio.CancelledError:

                        pass

                    except Exception as erro:

                        print()

                        print(
                            "[REALTIME] "
                            f"Tarefa encerrada com erro: {erro}"
                        )

                        print()


                for tarefa in pendente:

                    tarefa.cancel()


                if pendente:

                    await asyncio.gather(

                        *pendente,

                        return_exceptions=True

                    )


            finally:

                for tarefa in (

                    tarefa_microfone,

                    tarefa_eventos,

                    tarefa_aguardar_encerramento

                ):

                    if not tarefa.done():

                        tarefa.cancel()


                await asyncio.gather(

                    tarefa_microfone,

                    tarefa_eventos,

                    tarefa_aguardar_encerramento,

                    return_exceptions=True

                )


    except Exception as erro:

        print()

        print(
            "=" * 60
        )

        print(
            "ERRO NA SESSÃO REALTIME"
        )

        print(
            "=" * 60
        )

        print()

        print(
            repr(erro)
        )

        print()


    finally:

        # ====================================================
        # PARAR REALTIME
        # ====================================================

        REALTIME_ATIVO = False

        MICROFONE_ATIVO = False


        # ====================================================
        # PARAR MICROFONE
        # ====================================================

        if input_stream is not None:

            try:

                input_stream.stop()

            except Exception:

                pass


            try:

                input_stream.close()

            except Exception:

                pass


            input_stream = None


        # ====================================================
        # PARAR PLAYER
        # ====================================================

        if player is not None:

            try:

                player.stop()

            except Exception:

                pass


            try:

                player.close()

            except Exception:

                pass


            player = None


        # ====================================================
        # LIMPEZA
        # ====================================================

        SESSION = None

        limpar_audio()


        with itens_lock:

            itens_cancelados.clear()

            item_audio_atual = None


        duque_falando = False

        inicio_fala_duque = None

        audio_interrompido = False

        tracker = None


        # ----------------------------------------------------
        # Descarta a fila da sessão atual.
        # ----------------------------------------------------

        fila_microfone = None

        encerramento_evento = None

        LOOP = None


        resetar_processamento_voz()


        # ====================================================
        # VOLTA AO STANDBY
        # ====================================================

        print()

        print(
            "=" * 60
        )

        print(
            "REALTIME ENCERRADO"
        )

        print(
            "DUQUE EM STANDBY"
        )

        print(
            "=" * 60
        )

        print()


        mudar_estado(

            "standby",

            "Sistema online"

        )


# ============================================================
# WAKE WORD
# ============================================================

def iniciar_wakeword():

    print()

    print(
        "=" * 60
    )

    print(
        "DUQUE — WAKE WORD"
    )

    print(
        "=" * 60
    )

    print()

    print(
        f"Wake word: {WAKEWORD}"
    )

    print(
        f"Limiar: {LIMIAR}"
    )

    print()

    mudar_estado(

        "standby",

        "Sistema online"

    )


    try:

        modelo_wake = Model(

            wakeword_models=[

                WAKEWORD

            ]

        )

    except Exception as erro:

        print()

        print(
            "ERRO AO CARREGAR WAKE WORD:"
        )

        print(
            repr(erro)
        )

        print()

        return


    recorder = None


    try:

        # ====================================================
        # CRIAR WAKE WORD INICIAL
        # ====================================================

        recorder = PvRecorder(

            frame_length=FRAME_LENGTH,

            device_index=0

        )


        recorder.start()


        print(
            "Wake word ativo."
        )

        print(
            'Fale: "Hey Jarvis"'
        )

        print()


        ultimo_wake = 0.0


        while True:

            frame = recorder.read()


            audio = np.array(

                frame,

                dtype=np.int16

            )


            predicoes = modelo_wake.predict(
                audio
            )


            confianca = predicoes.get(

                WAKEWORD,

                0.0

            )


            agora = time.perf_counter()


            if (

                confianca >= LIMIAR

                and (

                    agora - ultimo_wake
                    >= COOLDOWN

                )

            ):

                ultimo_wake = agora


                print()

                print(
                    "=" * 60
                )

                print(
                    ">>> HEY JARVIS DETECTADO <<<"
                )

                print(
                    "=" * 60
                )

                print()


                # =================================================
                # DESLIGA E DESTRÓI O WAKE WORD ATUAL
                # =================================================

                try:

                    recorder.stop()

                except Exception:

                    pass


                try:

                    recorder.delete()

                except Exception:

                    pass


                recorder = None


                mudar_estado(

                    "ouvindo",

                    "Ativando Duque..."

                )


                # =================================================
                # REALTIME ASSUME
                # =================================================

                try:

                    asyncio.run(

                        executar_realtime()

                    )

                except KeyboardInterrupt:

                    raise


                except Exception as erro:

                    print()

                    print(
                        "[WAKE] Erro no Realtime:"
                    )

                    print(
                        repr(erro)
                    )

                    print()


                # =================================================
                # VOLTA AO STANDBY
                # =================================================

                print()

                print(
                    "Retornando ao modo standby..."
                )

                print()


                mudar_estado(

                    "standby",

                    "Sistema online"

                )


                # =================================================
                # CRIA UM NOVO PVRECORDER
                # =================================================

                try:

                    recorder = PvRecorder(

                        frame_length=FRAME_LENGTH,

                        device_index=0

                    )


                    recorder.start()


                    print(
                        'Wake word novamente ativo. '
                        'Fale "Hey Jarvis".'
                    )

                    print()


                except Exception as erro:

                    print()

                    print(
                        "[WAKE] Erro ao criar novo recorder:"
                    )

                    print(
                        repr(erro)
                    )

                    print()


                    break


    except KeyboardInterrupt:

        print()

        print(
            "Wake word encerrado."
        )

        print()


    except Exception as erro:

        print()

        print(
            "=" * 60
        )

        print(
            "ERRO NO WAKE WORD"
        )

        print(
            "=" * 60
        )

        print()

        print(
            repr(erro)
        )

        print()


    finally:

        if recorder is not None:

            try:

                recorder.stop()

            except Exception:

                pass


            try:

                recorder.delete()

            except Exception:

                pass


        mudar_estado(

            "standby",

            "Sistema offline"

        )


# ============================================================
# MAIN
# ============================================================

def main():

    print()

    print(
        "=" * 60
    )

    print(
        "DUQUE"
    )

    print(
        "=" * 60
    )

    print()


    print(
        f"Modelo Realtime: {MODEL}"
    )

    print(
        f"Microfone Realtime: {MICROFONE}"
    )

    print(
        f"Voz: {VOICE}"
    )

    print()


    print(
        "VAD servidor: ATIVO"
    )

    print(
        "VAD local: ATIVO"
    )

    print(
        "Interrupção imediata: ATIVA"
    )

    print(
        "Playback tracker: ATIVO"
    )

    print(
        "Processamento de voz: ATIVO"
    )

    print()


    print(
        "Fluxo:"
    )

    print(
        "STANDBY → HEY JARVIS → REALTIME"
    )

    print(
        "→ CONVERSA → ATÉ MAIS DUQUE → STANDBY"
    )

    print()


    mudar_estado(

        "standby",

        "Sistema online"

    )


    iniciar_wakeword()


# ============================================================
# EXECUÇÃO
# ============================================================

if __name__ == "__main__":

    try:

        main()


    except KeyboardInterrupt:

        print()

        print()

        print(
            "Duque encerrado."
        )

        print()


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
            "ERRO FATAL"
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