@echo off
rem Faz o TELEX NAO iniciar mais junto com o Windows.
set "ATALHO=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\TELEX.lnk"
if exist "%ATALHO%" (
    del "%ATALHO%"
    echo Pronto. O TELEX nao inicia mais junto com o Windows.
) else (
    echo O TELEX ja nao estava no inicio automatico.
)
echo.
pause
