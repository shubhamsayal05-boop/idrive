@echo off
title ODRIV - Convert shared .accdb to SQLite
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.11+ is required. Install it from python.org ^(tick "Add to PATH"^).
  pause
  exit /b 1
)
if not exist .venv (
  echo Creating environment...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
if not exist .venv\deps_ok (
  echo Installing dependencies ^(one time^)...
  python -m pip install --upgrade pip --quiet
  pip install -r backend\requirements.txt
  if errorlevel 1 (
    echo Dependency installation failed.
    pause
    exit /b 1
  )
  type nul > .venv\deps_ok
)
set /p FOLDER="Folder containing _OdrivDB.accdb (e.g. Y:\Odriv DB\db): "
set /p YEAR="Year subfolder (e.g. 2024, or leave blank): "
if "%YEAR%"=="" (
  python convert_shared_folder_to_sqlite.py "%FOLDER%"
) else (
  python convert_shared_folder_to_sqlite.py "%FOLDER%" %YEAR%
)
echo.
pause
