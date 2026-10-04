@echo off
cd /d "%~dp0"
echo Parando o Duque...
powershell -NoProfile -Command "Get-Process pythonw,python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like \"*$((Get-Location).Path)*\" } | Stop-Process -Force"
ping -n 3 127.0.0.1 >nul
echo Iniciando com a configuracao atual...
call "%~dp0iniciar_duque.bat"
