import pyttsx3

voz = pyttsx3.init()

voz.setProperty("rate", 175)
voz.setProperty("volume", 1.0)

voz.say("Olá, Du. Aqui é o Duque. Sistema de voz funcionando.")
voz.runAndWait()

print("✅ Teste de voz concluído.")