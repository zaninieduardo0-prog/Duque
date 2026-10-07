@echo off
cd /d "%~dp0"
call "%~dp0parar_duque.bat"
ping -n 3 127.0.0.1 >nul
echo Iniciando com a configuracao atual...
call "%~dp0iniciar_duque.bat"
