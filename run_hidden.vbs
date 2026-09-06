' Whisper Dictate - headless launcher with zero console flash.
' Usage: double-click this file, or point the Windows Startup shortcut at it:
'   wscript.exe "C:\Users\Richard\Documents\Projects\whisper-dictate\run_hidden.vbs"
' (Unlike run.bat, no cmd.exe window appears at all, not even briefly.)
Option Explicit
Dim sh, fso, dir
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.Run """" & dir & "\.venv\Scripts\pythonw.exe"" """ & dir & "\launcher.py"" --headless", 0, False
