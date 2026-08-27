Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
sh.Run "py -m pip install -r requirements.txt --disable-pip-version-check --no-input", 0, True
sh.Run "pyw ZakazkyCRM.pyw", 0, False
