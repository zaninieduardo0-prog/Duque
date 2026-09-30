import os
import tempfile
import time
import pygame
from openai import OpenAI

client = OpenAI()

def falar(texto):
    print(f"[TTS] Gerando áudio para: '{texto}'...")
    try:
        response = client.audio.speech.create(
            model="tts-1",
            voice="alloy",
            input=texto,
            response_format="mp3"
        )
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
            tmp.write(response.content)
            temp_path = tmp.name

        print(f"[TTS] Áudio salvo em: {temp_path}")
        print("[TTS] Reproduzindo...")

        # Inicializa e toca o áudio via pygame
        pygame.mixer.init()
        pygame.mixer.music.load(temp_path)
        pygame.mixer.music.play()

        # Aguarda terminar a reprodução antes de prosseguir
        while pygame.mixer.music.get_busy():
            time.sleep(0.1)

        pygame.mixer.quit()

        if os.path.exists(temp_path):
            os.remove(temp_path)

        print("[TTS] Concluído com sucesso!")

    except Exception as e:
        print(f"[TTS Erro Python]: {e}")