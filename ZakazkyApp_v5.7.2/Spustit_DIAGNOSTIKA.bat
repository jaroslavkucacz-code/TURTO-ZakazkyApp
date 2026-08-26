@echo off
cd /d "%~dp0"
py app.py
echo.
echo Kod ukonceni: %errorlevel%
pause
