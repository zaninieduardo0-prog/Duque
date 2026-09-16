import numpy as np
import openwakeword
from openwakeword.model import Model
from pvrecorder import PvRecorder


# ==========================================
# CONFIGURAÇÕES
# ==========================================

MICROFONE = 0
FRAME_LENGTH = 1280
LIMIAR = 0.5


# ==========================================
# MODELO
# ==========================================

print("🧠 Carregando modelo...")

modelo = Model(
    wakeword_models=["hey_jarvis"],
    inference_framework="onnx",
    vad_threshold=0.5
)


# ==========================================
# MICROFONE
# ==========================================

gravador = PvRecorder(
    device_index=MICROFONE,
    frame_length=FRAME_LENGTH
)

gravador.start()

print("\n==========================================")
print("🎙️ WAKE WORD ATIVO")
print("==========================================")
print("Fale: Hey Jarvis")
print("Pressione Ctrl+C para sair.\n")


# ==========================================
# ESCUTA
# ==========================================

try:

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

        if pontuacao > LIMIAR:

            print(
                f"\n🟢 WAKE WORD DETECTADO!"
                f"  Pontuação: {pontuacao:.2f}\n"
            )

except KeyboardInterrupt:

    print("\n\n🛑 Encerrando...")

finally:

    gravador.stop()
    gravador.delete()

    print("Teste encerrado.")