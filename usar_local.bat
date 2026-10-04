@echo off
chcp 65001 >nul
echo Modo local: ouvido Vosk, cerebro Ollama (se estiver no ar; OpenAI so de reserva) e voz Piper.
setx DUQUE_VOICE local >nul
setx DUQUE_BRAIN auto >nul
echo Pronto. Feche o Duque e abra de novo pelo iniciar_duque.bat.
pause
