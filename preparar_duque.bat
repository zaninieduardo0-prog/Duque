@echo off
rem Prepara (ou atualiza) o TELEX (pasta do Duque): cria a .venv se faltar, instala as
rem dependências, baixa o modelo da wake word e roda o diagnóstico.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Criando ambiente virtual .venv ...
    py -3 -m venv .venv || python -m venv .venv
)

echo Instalando dependencias...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -e . pytest

echo Conferindo o modelo da wake word...
".venv\Scripts\python.exe" -c "import openwakeword.utils as u; u.download_models(['hey_jarvis'])"

echo Conferindo a ativacao "Bom dia, TELEX" (modelo local de portugues, ~50 MB)...
".venv\Scripts\python.exe" -m voice.local_wake --baixar

echo.
".venv\Scripts\python.exe" diagnostico.py --testes
echo.
pause
