@echo off
REM Build a standalone WhispLocal folder with PyInstaller:
REM   dist\WhispLocal\WhispLocal.exe
REM Uses its own virtual environment (build-venv) so the app venv is untouched.
REM Usage: packaging\build.bat [--skip-self-test]
setlocal
cd /d "%~dp0\.."

if not exist build-venv\Scripts\python.exe (
    echo Creating build environment...
    py -3.11 -m venv build-venv 2>nul || py -3 -m venv build-venv 2>nul || python -m venv build-venv
)
if not exist build-venv\Scripts\python.exe (
    echo ERROR: Python 3 was not found. Install it from https://www.python.org/downloads/
    exit /b 1
)

echo Installing dependencies...
build-venv\Scripts\python.exe -m pip install --disable-pip-version-check -q -r requirements.txt -r packaging\requirements-build.txt
if errorlevel 1 (
    echo ERROR: dependency installation failed.
    exit /b 1
)

echo Building with PyInstaller...
build-venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging\whisplocal.spec
if errorlevel 1 (
    echo ERROR: PyInstaller build failed.
    exit /b 1
)

if "%~1"=="--skip-self-test" goto done
echo Running the self-test of the built app...
start "" /wait dist\WhispLocal\WhispLocal.exe --self-test
set RESULT=%ERRORLEVEL%
type dist\WhispLocal\self-test.txt
if not "%RESULT%"=="0" (
    echo ERROR: the built app failed its self-test ^(see above^).
    exit /b 1
)

:done
echo.
echo Build complete: dist\WhispLocal\WhispLocal.exe
echo Copy the whole dist\WhispLocal folder somewhere writable, e.g. %%LOCALAPPDATA%%\WhispLocal.
endlocal
