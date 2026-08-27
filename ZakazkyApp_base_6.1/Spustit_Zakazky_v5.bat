@echo off
setlocal
cd /d "%~dp0"
title ZakazkyApp v5.2
where pyw >nul 2>nul
if not errorlevel 1 (
  start "" /b pyw app.py
  exit /b 0
)
echo Nenalezen pyw. Spoustim diagnosticky pres py...
py app.py 2>v5_error.log
if errorlevel 1 (
  echo.
  echo Program skoncil chybou. Viz v5_error.log
  type v5_error.log
  pause
)
endlocal
