@echo off
setlocal
cd /d "%~dp0"

set "VENV_PYW=.venv\Scripts\pythonw.exe"
set "VENV_PY=.venv\Scripts\python.exe"

REM 1) The venv must exist. If not, the user hasn't run setup yet.
if not exist "%VENV_PYW%" (
    echo(
    echo Rekounts is not set up yet.
    echo   The virtual environment ".venv" was not found.
    echo   Double-click setup.bat first, then run this again.
    echo(
    pause
    exit /b 1
)

REM 2) Refuse to launch on Python older than 3.11 (faster-whisper / PySide6 need it).
"%VENV_PY%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 (
    echo(
    echo Rekounts needs Python 3.11 or newer, but .venv was built with an older one.
    echo   Delete the .venv folder and run setup.bat again with Python 3.11+.
    echo(
    pause
    exit /b 1
)

REM 3) Launch detached with the windowless interpreter (no lingering console).
start "" "%VENV_PYW%" -m rekounts
