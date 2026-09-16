import sounddevice as sd

DURACAO = 5
TAXA = 44100

print("🎙️ Pode falar! Gravando por 5 segundos...")

audio = sd.rec(
    int(DURACAO * TAXA),
    samplerate=TAXA,
    channels=1,
    dtype="float32",
    device=1
)

sd.wait()

print("🔊 Reproduzindo...")

sd.play(audio, TAXA)
sd.wait()

print("✅ Teste concluído.")