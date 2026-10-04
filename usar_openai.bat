@echo off
chcp 65001 >nul
echo Modo OpenAI: voz e cerebro pela API (precisa de creditos na conta).
setx DUQUE_VOICE openai >nul
setx DUQUE_BRAIN openai >nul
echo Pronto. Feche o Duque e abra de novo pelo iniciar_duque.bat.
pause
