@echo off
title ODRIV
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.11+ is required. Install it from python.org ^(tick "Add to PATH"^) and run this again.
  pause
  exit /b 1
)
if not exist .venv (
  echo Creating environment...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
if not exist .venv\deps_ok (
  echo Installing dependencies ^(one time, a few minutes^)...
  python -m pip install --upgrade pip --quiet
  pip install -r backend\requirements.txt
  if errorlevel 1 (
    echo.
    echo Dependency installation failed - check your internet connection and run this again.
    pause
    exit /b 1
  )
  type nul > .venv\deps_ok
)
echo Starting ODRIV ^(builds the UI on first run if Node.js is installed^)...
python run_odriv.py
echo.
echo ODRIV stopped.
pause
