@echo off
title DUQUE AI

cd /d C:\Duque

set PYTHON=C:\Duque\.venv\Scripts\python.exe

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
echo Python:
echo %PYTHON%
echo.

if not exist "%PYTHON%" (
    echo ERRO: Python do ambiente virtual nao encontrado.
    echo.
    pause
    exit /b
)

echo Iniciando servidor...
echo.

start "DUQUE - SERVIDOR" cmd /k "cd /d C:\Duque && "%PYTHON%" servidor.py"

timeout /t 3 /nobreak >nul

echo Iniciando inteligencia artificial...
echo.

start "DUQUE - IA" cmd /k "cd /d C:\Duque && "%PYTHON%" duque_wake_v3.py"
timeout /t 4 /nobreak >nul

echo Abrindo interface...
echo.

start "" "http://127.0.0.1:5000"
echo.
echo ==========================================
echo       DUQUE INICIADO COM SUCESSO
echo ==========================================
echo.
echo Pode fechar esta janela.
echo.
pause