' Silent launcher — starts WhispLocal with no console window.
' Put a shortcut to this file in shell:startup to launch on login.
Set fso = CreateObject("Scripting.FileSystemObject")
appDir = fso.GetParentFolderName(WScript.ScriptFullName)
Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = appDir
shell.Run """" & appDir & "\venv\Scripts\pythonw.exe"" """ & appDir & "\whisp\app.py""", 0, False
