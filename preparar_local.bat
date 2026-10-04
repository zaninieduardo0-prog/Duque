@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================================
echo  TELEX 100%% local: cerebro (Ollama) + voz (Piper)
echo ========================================================
echo.
echo [1/3] Voz do TELEX (Piper + voz pt-BR, ~80 MB)...
".venv\Scripts\python.exe" -m voice.local_tts --baixar faber
echo.
echo [2/3] Cerebro local (Ollama)...
where ollama >nul 2>nul
if errorlevel 1 (
    echo Ollama nao encontrado. Instalando pelo winget...
    winget install -e --id Ollama.Ollama --accept-package-agreements --accept-source-agreements
    echo.
    echo Feche e abra este arquivo de novo para o Windows enxergar o Ollama.
    pause
    exit /b 0
)
echo Baixando o modelo qwen2.5:3b (~2 GB, so na primeira vez)...
ollama pull qwen2.5:3b
echo.
echo [3/3] Ligando o modo local...
setx DUQUE_VOICE local >nul
setx DUQUE_BRAIN auto >nul
echo.
echo Pronto. Feche o Duque (se estiver aberto) e abra de novo pelo iniciar_duque.bat.
echo Para ouvir a voz agora:  .venv\Scripts\python.exe -m voice.local_tts --testar
pause
