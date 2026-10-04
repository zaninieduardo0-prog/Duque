@echo off
cd /d "%~dp0"
echo Parando o Duque...
rem Procura pela LINHA DE COMANDO (duque.py / duque_supervisor.py desta pasta), nao pelo
rem caminho do executavel: o python da .venv no Windows e so um lancador que abre o
rem Python "de verdade" como processo filho, fora desta pasta. Antes so o lancador
rem morria e o Duque antigo continuava rodando junto com o novo.
powershell -NoProfile -Command "$root=(Get-Location).Path; Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -and $_.CommandLine -like ('*' + $root + '*') -and ($_.CommandLine -like '*duque.py*' -or $_.CommandLine -like '*duque_supervisor.py*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
ping -n 3 127.0.0.1 >nul
echo Iniciando com a configuracao atual...
call "%~dp0iniciar_duque.bat"
