import numpy as np
from openwakeword.model import Model
from pvrecorder import PvRecorder
import speech_recognition as sr
import re
import time
import subprocess
import sys
import urllib.request

from agents import Runner, SQLiteSession
from agent.duque import duque


# ============================================================
# CONFIGURAÇÕES
# ============================================================

MICROFONE = 0
FRAME_LENGTH = 1280

# Sensibilidade do "Hey Jarvis"
LIMIAR = 0.5

# Servidor da interface
SERVIDOR = "http://127.0.0.1:5000"

# Tempo de proteção contra nova ativação
COOLDOWN = 2

# Tempo mínimo de silêncio antes de rearmar
TEMPO_SILENCIO = 1.2

# Tempo máximo esperando você começar a falar
TIMEOUT_COMANDO = 4

# Tempo máximo da frase
TEMPO_MAXIMO_FALA = 12


# ============================================================
# COMUNICAÇÃO COM A INTERFACE
# ============================================================

def mudar_estado(estado):
    try:
        resposta = urllib.request.urlopen(
            f"{SERVIDOR}/estado/{estado}",
            timeout=0.5
        )
        resposta.close()
    except:
        pass


# ============================================================
# LIMPEZA DA RESPOSTA PARA TTS
# ============================================================

def limpar_para_fala(texto):

    texto = re.sub(
        r"```.*?```",
        "",
        texto,
        flags=re.DOTALL
    )

    texto = texto.replace("**", "")
    texto = texto.replace("__", "")
    texto = texto.replace("*", "")
    texto = texto.replace("_", "")

    texto = re.sub(
        r"#+\s*",
        "",
        texto
    )

    texto = re.sub(
        r"\[([^\]]+)\]\([^)]+\)",
        r"\1",
        texto
    )

    texto = re.sub(
        r"\s+",
        " ",
        texto
    )

    return texto.strip()


# ============================================================
# VOZ
# ============================================================

def falar(texto):

    print(f"\nDuque: {texto}")

    mudar_estado("falando")

    texto_falado = limpar_para_fala(texto)

    codigo = f'''
import pyttsx3

voz = pyttsx3.init()

voz.setProperty("rate", 185)
voz.setProperty("volume", 1.0)

voz.say({texto_falado!r})

voz.runAndWait()
voz.stop()
'''

    subprocess.run(
        [sys.executable, "-c", codigo],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    time.sleep(0.15)


# ============================================================
# RECONHECIMENTO DE VOZ
# ============================================================

reconhecedor = sr.Recognizer()

# Menor tolerância para pausas longas
reconhecedor.pause_threshold = 0.6

# Pequeno tempo antes de considerar que começou a fala
reconhecedor.phrase_threshold = 0.25

# Energia mínima dinâmica
reconhecedor.dynamic_energy_threshold = True


def ouvir_comando():

    mudar_estado("ouvindo")

    with sr.Microphone(
        device_index=MICROFONE
    ) as microfone:

        print("\n🎙️ Estou ouvindo...")

        # Ajuste rápido do ruído ambiente
        try:
            reconhecedor.adjust_for_ambient_noise(
                microfone,
                duration=0.15
            )
        except:
            pass

        try:

            inicio = time.time()

            audio = reconhecedor.listen(
                microfone,

                # Quanto tempo esperamos você começar
                timeout=TIMEOUT_COMANDO,

                # Depois que começar, quanto pode durar
                phrase_time_limit=TEMPO_MAXIMO_FALA
            )

            tempo_captura = time.time() - inicio

            print(
                f"🎙️ Áudio capturado em "
                f"{tempo_captura:.2f}s"
            )

        except sr.WaitTimeoutError:

            print(
                "\n😴 Você não falou nada."
            )

            return ""

        except Exception as erro:

            print(
                f"\n❌ Erro no microfone: {erro}"
            )

            return ""

    mudar_estado("processando")

    print("\n🧠 Entendendo...")

    try:

        inicio = time.time()

        texto = reconhecedor.recognize_google(
            audio,
            language="pt-BR"
        )

        tempo_reconhecimento = time.time() - inicio

        print(
            f"📝 Reconhecido em "
            f"{tempo_reconhecimento:.2f}s"
        )

        print(
            f"Du: {texto}"
        )

        return texto

    except sr.UnknownValueError:

        print(
            "❌ Não consegui entender."
        )

        return ""

    except sr.RequestError as erro:

        print(
            f"❌ Erro no reconhecimento: {erro}"
        )

        return ""


# ============================================================
# WAKE WORD
# ============================================================

print(
    "🧠 Carregando modelo de wake word..."
)

modelo = Model(
    wakeword_models=["hey_jarvis"],
    inference_framework="onnx",
    vad_threshold=0.5
)


# ============================================================
# MEMÓRIA DA SESSÃO
# ============================================================

session = SQLiteSession(
    "duque_memoria_wake"
)


# ============================================================
# INICIALIZAÇÃO
# ============================================================

print("\n==========================================")
print("🤖 DUQUE")
print("==========================================")
print("Wake word: Hey Jarvis")
print("Diga 'Hey Jarvis' para me chamar.")
print("Pressione Ctrl+C para sair.")
print("==========================================\n")


mudar_estado("standby")


# ============================================================
# GRAVADOR
# ============================================================

gravador = PvRecorder(
    device_index=MICROFONE,
    frame_length=FRAME_LENGTH
)


# ============================================================
# AGUARDAR AMBIENTE SILENCIOSO
# ============================================================

def esperar_silencio():

    print(
        "\n🔇 Aguardando o ambiente ficar silencioso..."
    )

    inicio_silencio = None

    while True:

        audio = gravador.read()

        audio = np.array(
            audio,
            dtype=np.int16
        )

        previsao = modelo.predict(audio)

        pontuacao = previsao.get(
            "hey_jarvis",
            0
        )

        if pontuacao >= LIMIAR:

            inicio_silencio = None

            continue

        if inicio_silencio is None:

            inicio_silencio = time.time()

        if (
            time.time() - inicio_silencio
            >= TEMPO_SILENCIO
        ):

            print(
                "✅ Ambiente liberado."
            )

            return


# ============================================================
# ATENDER DU
# ============================================================

def atender_du():

    print(
        "\n🟢 DUQUE ACORDOU!"
    )

    # --------------------------------------------------------
    # Para o detector de wake word.
    # --------------------------------------------------------

    try:
        gravador.stop()
    except:
        pass

    # Pequena pausa para liberar o dispositivo
    time.sleep(0.15)

    # --------------------------------------------------------
    # Resposta rápida
    # --------------------------------------------------------

    falar(
        "Pois não, Du."
    )

    # --------------------------------------------------------
    # Assim que terminar, já começa a ouvir.
    # --------------------------------------------------------

    comando = ouvir_comando()

    if not comando:

        print(
            "\n😴 Nenhum comando recebido."
        )

        mudar_estado(
            "aguardando"
        )

        return

    # --------------------------------------------------------
    # Comandos de encerramento
    # --------------------------------------------------------

    comando_lower = comando.lower().strip()

    if comando_lower in [
        "sair",
        "exit",
        "quit",
        "encerrar",
        "desligar o duque"
    ]:

        falar(
            "Até mais, Du."
        )

        raise SystemExit

    # --------------------------------------------------------
    # PROCESSAMENTO
    # --------------------------------------------------------

    print(
        "\n🧠 Duque processando..."
    )

    mudar_estado(
        "processando"
    )

    inicio_processamento = time.time()

    try:

        resultado = Runner.run_sync(
            duque,
            comando,
            session=session
        )

        tempo_processamento = (
            time.time()
            - inicio_processamento
        )

        print(
            f"\n⏱️ Processamento: "
            f"{tempo_processamento:.2f}s"
        )

        resposta = resultado.final_output

        # ----------------------------------------------------
        # Resposta
        # ----------------------------------------------------

        falar(
            resposta
        )

    except Exception as erro:

        print(
            f"\n❌ ERRO:\n{erro}"
        )

        falar(
            "Tive um problema ao processar essa solicitação."
        )

    # --------------------------------------------------------
    # Volta para espera
    # --------------------------------------------------------

    mudar_estado(
        "aguardando"
    )


# ============================================================
# LOOP PRINCIPAL
# ============================================================

try:

    gravador.start()

    print(
        "\n👂 Duque está aguardando..."
    )

    while True:

        audio = gravador.read()

        audio = np.array(
            audio,
            dtype=np.int16
        )

        previsao = modelo.predict(
            audio
        )

        pontuacao = previsao.get(
            "hey_jarvis",
            0
        )

        # ----------------------------------------------------
        # WAKE WORD DETECTADO
        # ----------------------------------------------------

        if pontuacao >= LIMIAR:

            print(
                f"\n🟢 Wake word detectado! "
                f"Pontuação: {pontuacao:.2f}"
            )

            atender_du()

            # ------------------------------------------------
            # Pequeno cooldown
            # ------------------------------------------------

            print(
                f"\n⏳ Cooldown de {COOLDOWN}s..."
            )

            time.sleep(
                COOLDOWN
            )

            # ------------------------------------------------
            # Reinicia detector
            # ------------------------------------------------

            try:
                gravador.start()
            except:
                pass

            # ------------------------------------------------
            # Espera o ambiente estabilizar
            # ------------------------------------------------

            esperar_silencio()

            mudar_estado(
                "aguardando"
            )

            print(
                "\n👂 Duque está aguardando..."
            )


# ============================================================
# ENCERRAMENTO
# ============================================================

except KeyboardInterrupt:

    print(
        "\n\n🛑 Duque encerrado."
    )

except SystemExit:

    print(
        "\n\n🛑 Duque encerrado."
    )

finally:

    try:
        gravador.stop()
    except:
        pass

    try:
        gravador.delete()
    except:
        pass

    mudar_estado(
        "standby"
    )

    print(
        "\nSistema encerrado."
    )