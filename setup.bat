@echo off
REM One-time setup: create venv, install dependencies, download the model.
cd /d "%~dp0"

echo Creating virtual environment...
py -3.11 -m venv venv 2>nul || py -3 -m venv venv 2>nul || python -m venv venv
if not exist venv\Scripts\python.exe (
    echo.
    echo ERROR: Python 3 was not found. Install it from https://www.python.org/downloads/
    echo        ^(check "Add python.exe to PATH" during install^) and re-run setup.bat.
    pause
    exit /b 1
)

echo Installing dependencies (this can take a few minutes)...
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERROR: dependency installation failed. Check your internet connection
    echo        and re-run setup.bat.
    pause
    exit /b 1
)

echo Downloading the speech model (one-time, ~75 MB)...
venv\Scripts\python.exe warmup.py
if errorlevel 1 (
    echo.
    echo ERROR: model download failed. Check your internet connection and
    echo        re-run setup.bat.
    pause
    exit /b 1
)

echo.
echo Setup complete. Run install_shortcuts.bat to add the app to your
echo Desktop and Start Menu, then launch WhispLocal from there.
pause
