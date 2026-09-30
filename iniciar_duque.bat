@echo off
title DUQUE AI

rem Usa automaticamente a pasta onde este .bat estiver.
cd /d "%~dp0"

set PYTHON=python

rem Workspace do agente: por padrao, o proprio projeto Duque.
rem Pode ser sobrescrito antes de iniciar para apontar para outra pasta.
set DUQUE_WORKSPACE=%~dp0

rem Desenvolvimento autonomo: o Duque pode ler, alterar e executar o proprio codigo.
rem Deixe 0 para modo normal. Para autonomia de desenvolvimento, use 1 nos dois.
set DUQUE_AUTONOMOUS_AGENT=1
set DUQUE_ALLOW_SELF_MODIFICATION=0
set DUQUE_MODEL=gpt-5

rem Configuracao de voz: altere estas variaveis sem mexer no runtime.
set DUQUE_VOICE=cedar
set DUQUE_PITCH=-2.0
set DUQUE_VOICE_SPEED=0.96
rem Desligado por padrao para preservar a voz natural do Realtime.
set DUQUE_VOICE_PROCESSING=0

echo ==========================================
echo              DUQUE AI
echo ==========================================
echo.
echo Pasta:
echo %CD%
echo.

where %PYTHON% >nul 2>&1
if errorlevel 1 (
    echo ERRO: Python nao encontrado no PATH.
    echo.
    timeout /t 2 /nobreak >nul
    exit /b
)

echo Iniciando servidor...
echo.

start "DUQUE - SERVIDOR" cmd /k "cd /d "%~dp0" && %PYTHON% servidor.py"

timeout /t 3 /nobreak >nul

echo Iniciando inteligencia artificial...
echo.

start "DUQUE - IA" cmd /k "cd /d "%~dp0" && %PYTHON% duque_wake_v3.py"
timeout /t 4 /nobreak >nul

echo Abrindo interface...
echo.

start "" "http://127.0.0.1:5000"
echo.
echo ==========================================
echo       DUQUE INICIADO COM SUCESSO
echo ==========================================
echo.
echo O Duque fica disponivel pela interface.
echo.
pause