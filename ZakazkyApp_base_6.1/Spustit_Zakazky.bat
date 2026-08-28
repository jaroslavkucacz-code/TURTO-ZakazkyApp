@echo off
cd /d "%~dp0"
REM Compatibility launcher: never run app.py directly.
REM All historical shortcuts that point to this BAT are forwarded to the
REM canonical runtime entry point generated in every published package.
if exist "%~dp0Spustit_Zakazky.vbs" (
  wscript.exe "%~dp0Spustit_Zakazky.vbs"
  exit /b
)
where pyw >nul 2>nul
if %errorlevel%==0 (
  start "" pyw "%~dp0ZakazkyCRM.pyw"
  exit /b
)
where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw "%~dp0ZakazkyCRM.pyw"
  exit /b
)
py "%~dp0ZakazkyCRM.pyw"
