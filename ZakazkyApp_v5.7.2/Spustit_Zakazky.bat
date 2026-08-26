@echo off
cd /d "%~dp0"
where pyw >nul 2>nul
if %errorlevel%==0 (
  start "" pyw app.py
  exit /b
)
where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw app.py
  exit /b
)
py app.py
