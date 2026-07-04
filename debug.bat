@echo off
REM Troubleshooting launcher WITH a console window (normal use: the
REM WhispLocal shortcut / WhispLocal.vbs, which runs silently).
cd /d "%~dp0"
venv\Scripts\python.exe whisp\app.py
pause
