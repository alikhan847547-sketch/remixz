' RemixZ Cleaner X — sin ventana CMD, solo pantalla de carga + Cleaner
Option Explicit
Dim sh, fso, dir, pyw, py, script, cmd
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
script = dir & "\RemixZ_Cleaner_X_App.py"

' Preferir pythonw (sin consola)
pyw = ""
py = ""
On Error Resume Next
pyw = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Python312\pythonw.exe"
If Not fso.FileExists(pyw) Then pyw = "pythonw.exe"
py = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Python312\python.exe"
If Not fso.FileExists(py) Then py = "python.exe"
On Error GoTo 0

sh.CurrentDirectory = dir

If fso.FileExists(Replace(pyw, "pythonw.exe", "pythonw.exe")) Or True Then
  ' 0 = oculto
  cmd = """" & pyw & """ """ & script & """"
  sh.Run cmd, 0, False
Else
  cmd = """" & py & """ """ & script & """"
  sh.Run cmd, 0, False
End If
