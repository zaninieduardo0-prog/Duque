import speech_recognition as sr

reconhecedor = sr.Recognizer()

with sr.Microphone(device_index=1) as microfone:

    print("🎙️ Ajustando o microfone...")
    reconhecedor.adjust_for_ambient_noise(microfone, duration=1)

    print("\n🎙️ Pode falar...")
    audio = reconhecedor.listen(microfone)

print("🧠 Entendendo...")

try:
    texto = reconhecedor.recognize_google(
        audio,
        language="pt-BR"
    )

    print(f"\nVocê disse: {texto}")

except sr.UnknownValueError:
    print("\n❌ Não consegui entender o que você falou.")

except sr.RequestError as erro:
    print(f"\n❌ Erro no serviço de reconhecimento: {erro}")