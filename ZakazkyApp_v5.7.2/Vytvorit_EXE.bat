@echo off
cd /d "%~dp0"
py -m pip install --upgrade pyinstaller
py -m PyInstaller --noconfirm --clean --onefile --windowed --add-data "turto_logo.png;." --name Zakazky app.py
pause
