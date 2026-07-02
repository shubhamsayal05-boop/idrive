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
echo Installing converter dependencies ^(one time, needs internet^)...
python -m pip install --upgrade pip --quiet
pip install access-parser
if errorlevel 1 (
  echo.
  echo Failed to install access-parser. Check your internet / proxy and run again.
  pause
  exit /b 1
)
set /p FOLDER="Folder containing _OdrivDB.accdb (e.g. Y:\Odriv DB\db): "
set /p YEAR="Year subfolder (e.g. 2024, or leave blank): "
echo.
if "%YEAR%"=="" (
  python convert_shared_folder_to_sqlite.py "%FOLDER%"
) else (
  python convert_shared_folder_to_sqlite.py "%FOLDER%" %YEAR%
)
if errorlevel 1 (
  echo.
  echo Conversion failed. See the error above.
) else (
  echo.
  echo Conversion finished successfully.
)
echo.
pause
