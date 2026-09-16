import re
import speech_recognition as sr
import pyttsx3

from agents import Runner, SQLiteSession
from agent.duque import duque


# ==========================================
# CONFIGURAÇÕES
# ==========================================

MICROFONE = 1


# ==========================================
# LIMPAR TEXTO PARA A FALA
# ==========================================

def limpar_para_fala(texto):

    # Remove blocos de código
    texto = re.sub(r"```.*?```", "", texto, flags=re.DOTALL)

    # Remove negrito e itálico do Markdown
    texto = texto.replace("**", "")
    texto = texto.replace("__", "")
    texto = texto.replace("*", "")
    texto = texto.replace("_", "")

    # Remove títulos Markdown
    texto = re.sub(r"#+\s*", "", texto)

    # Remove links Markdown, mantendo apenas o texto
    texto = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", texto)

    # Remove espaços duplicados
    texto = re.sub(r"\s+", " ", texto)

    return texto.strip()


# ==========================================
# VOZ DO DUQUE
# ==========================================

def falar(texto):

    print(f"\nDuque: {texto}")

    texto_falado = limpar_para_fala(texto)

    voz = pyttsx3.init()

    voz.setProperty("rate", 175)
    voz.setProperty("volume", 1.0)

    voz.say(texto_falado)
    voz.runAndWait()
    voz.stop()


# ==========================================
# RECONHECIMENTO DE VOZ
# ==========================================

reconhecedor = sr.Recognizer()


def ouvir():

    with sr.Microphone(device_index=MICROFONE) as microfone:

        print("\n🎙️ Ouvindo...")

        audio = reconhecedor.listen(
            microfone,
            timeout=10,
            phrase_time_limit=15
        )

    print("🧠 Entendendo...")

    try:

        texto = reconhecedor.recognize_google(
            audio,
            language="pt-BR"
        )

        print(f"Você: {texto}")

        return texto

    except sr.UnknownValueError:

        print("❌ Não consegui entender.")

        return ""

    except sr.RequestError as erro:

        print(f"❌ Erro no reconhecimento: {erro}")

        return ""


# ==========================================
# MEMÓRIA
# ==========================================

session = SQLiteSession(
    "duque_memoria_voz"
)


# ==========================================
# INÍCIO
# ==========================================

falar("Olá, Du. Estou ouvindo.")


# ==========================================
# LOOP PRINCIPAL
# ==========================================

while True:

    try:

        pergunta = ouvir()

        if not pergunta:
            continue

        if pergunta.lower() in [
            "sair",
            "encerrar",
            "desligar o duque"
        ]:

            falar("Até mais, Du.")
            break

        resultado = Runner.run_sync(
            duque,
            pergunta,
            session=session
        )

        resposta = resultado.final_output

        falar(resposta)

    except KeyboardInterrupt:

        print("\n\nDuque encerrado.")
        break

    except Exception as erro:

        print(f"\n❌ ERRO:\n{erro}")

        falar(
            "Tive um problema ao processar essa solicitação."
        )