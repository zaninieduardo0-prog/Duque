Option Explicit

' Inicia o TELEX em modo oculto (sem interface, só ativação por voz).
' A interface abre sozinha quando o Du ativar a voz ("Bom dia, TELEX").
' Use este arquivo no início automático do Windows (iniciar_com_windows.bat).

Dim shell, fso, root, pythonw, env, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

root = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = root & "\.venv\Scripts\pythonw.exe"

If Not fso.FileExists(pythonw) Then
    WScript.Quit 1
End If

Set env = shell.Environment("PROCESS")
env("DUQUE_START_HIDDEN") = "1"

shell.CurrentDirectory = root
command = """" & pythonw & """ """ & root & "\duque_supervisor.py"""
shell.Run command, 0, False
