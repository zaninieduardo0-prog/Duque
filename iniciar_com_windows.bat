@echo off
rem Faz o TELEX iniciar junto com o Windows, em modo oculto (so voz).
rem De dois cliques neste arquivo UMA vez. Para desfazer, use parar_inicio_windows.bat.
setlocal
set "ALVO=%~dp0TELEX_oculto.vbs"
set "ATALHO=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\TELEX.lnk"
powershell -NoProfile -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%ATALHO%'); $s.TargetPath='wscript.exe'; $s.Arguments='\"%ALVO%\"'; $s.WorkingDirectory='%~dp0'; $s.WindowStyle=7; $s.Save()"
if exist "%ATALHO%" (
    echo Pronto. O TELEX vai iniciar junto com o Windows, so com a voz.
    echo A interface abre sozinha quando voce disser "Bom dia, TELEX".
) else (
    echo Nao consegui criar o atalho de inicio. Me avise.
)
echo.
pause
