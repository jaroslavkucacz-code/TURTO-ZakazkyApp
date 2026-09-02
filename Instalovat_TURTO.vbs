Option Explicit
Dim shell, fso, folder, scriptPath, candidates, candidate, checkCommand, rc, quote
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
scriptPath = folder & "\TURTO_install.py"
quote = Chr(34)
candidates = Array("pyw", "pythonw", "py", "python")
For Each candidate In candidates
    checkCommand = "cmd /d /c where " & candidate & " >nul 2>nul"
    rc = shell.Run(checkCommand, 0, True)
    If rc = 0 Then
        shell.CurrentDirectory = folder
        shell.Run candidate & " " & quote & scriptPath & quote, 0, False
        WScript.Quit 0
    End If
Next
MsgBox "Python was not found. Install 64-bit Python for Windows first.", vbCritical, "TURTO"
