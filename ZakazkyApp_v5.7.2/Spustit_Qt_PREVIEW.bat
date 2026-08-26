@echo off
cd /d "%~dp0"
py -m pip install --upgrade "PySide6>=6.10,<6.12"
py qt_preview_v5.py
pause
