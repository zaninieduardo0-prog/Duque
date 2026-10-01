import re
import speech_recognition as sr
import pyttsx3

from brain.agent_loop import AgentLoop


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

# Inicializa engine TTS uma vez
_TTS_ENGINE = pyttsx3.init()
_TTS_ENGINE.setProperty("rate", 175)
_TTS_ENGINE.setProperty("volume", 1.0)


def falar(texto: str) -> None:
    print(f"\nDuque: {texto}")
    texto_falado = limpar_para_fala(texto)
    _TTS_ENGINE.say(texto_falado)
    _TTS_ENGINE.runAndWait()


# ==========================================
# RECONHECIMENTO DE VOZ
# ==========================================

reconhecedor = sr.Recognizer()


def ouvir(device_index: int | None = MICROFONE) -> str:
    """Captura áudio do microfone e retorna o texto reconhecido (ou "" em falha)."""
    try:
        with sr.Microphone(device_index=device_index) as microfone:
            # calibra ruído ambiente
            reconhecedor.adjust_for_ambient_noise(microfone, duration=1)
            print("\n🎙️ Ouvindo...")
            try:
                audio = reconhecedor.listen(microfone, timeout=10, phrase_time_limit=20)
            except sr.WaitTimeoutError:
                print("⏱️ Timeout ao ouvir.")
                return ""
    except OSError as erro:
        print(f"❌ Erro ao abrir microfone (device_index={device_index}): {erro}")
        return ""

    print("🧠 Entendendo...")
    try:
        texto = reconhecedor.recognize_google(audio, language="pt-BR")
        print(f"Você: {texto}")
        return texto
    except sr.UnknownValueError:
        print("❌ Não consegui entender.")
        return ""
    except sr.RequestError as erro:
        print(f"❌ Erro no reconhecimento: {erro}")
        return ""


def listar_microfones() -> None:
    names = sr.Microphone.list_microphone_names()
    print("\nDispositivos de áudio disponíveis:")
    for i, name in enumerate(names):
        print(f"  {i}: {name}")


# ==========================================
# MEMÓRIA
# ==========================================


# ==========================================
# INÍCIO
# ==========================================

# ==========================================
# LOOP PRINCIPAL
# ==========================================
def main() -> None:
    """Loop de voz usando AgentLoop (API atual do projeto)."""
    agent = AgentLoop()

    # Mostra dispositivos e informa qual índice está configurado
    try:
        listar_microfones()
    except Exception:
        pass
    print(f"\nUsando microfone index: {MICROFONE}\n")

    falar("Olá, Du. Estou ouvindo.")

    while True:
        try:
            pergunta = ouvir()
            if not pergunta:
                continue

            if pergunta.lower() in ["sair", "encerrar", "desligar o duque"]:
                falar("Até mais, Du.")
                break

            resultado = agent.handle(pergunta)
            resposta = resultado.text
            falar(resposta)

        except KeyboardInterrupt:
            print("\n\nDuque encerrado.")
            break

        except Exception as erro:
            print(f"\n❌ ERRO:\n{erro}")
            falar("Tive um problema ao processar essa solicitação.")


if __name__ == "__main__":
    main()
