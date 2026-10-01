Option Explicit

Dim shell, fso, root, pythonw, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

root = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = root & "\.venv\Scripts\pythonw.exe"

If Not fso.FileExists(pythonw) Then
    MsgBox "Python da .venv não foi encontrado em:" & vbCrLf & pythonw, vbCritical, "Duque"
    WScript.Quit 1
End If

shell.CurrentDirectory = root
command = """" & pythonw & """ """ & root & "\duque.py"""
shell.Run command, 0, False
