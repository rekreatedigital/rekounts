@echo off
setlocal
cd /d "%~dp0"

echo Setting up Rekounts...
echo(

REM Find a real Python 3.11+ interpreter. Prefer the "py" launcher, then python,
REM then python3. The version probe below also skips the Microsoft Store alias
REM (a 0-byte stub in WindowsApps that opens the Store instead of running Python):
REM it fails the probe, so we fall through to the "not found" help text.
set "PY="
for %%C in ("py -3" "python" "python3") do (
    if not defined PY (
        %%~C -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
        if not errorlevel 1 set "PY=%%~C"
    )
)

if not defined PY (
    echo Could not find Python 3.11 or newer on this PC.
    echo(
    echo   1. Install Python 3.11+ from https://www.python.org/downloads/
    echo      ^(tick "Add Python to PATH" during install^).
    echo   2. If typing "python" opens the Microsoft Store, turn the alias off:
    echo      Settings ^> Apps ^> Advanced app settings ^> App execution aliases
    echo      ^> turn OFF "python.exe" and "python3.exe", then reopen this window.
    echo   3. Run setup.bat again.
    echo(
    pause
    exit /b 1
)

echo Using Python: %PY%
%PY% --version
echo(

echo Creating virtual environment (.venv)...
%PY% -m venv .venv
if errorlevel 1 (
    echo Failed to create the virtual environment ^(see the message above^).
    pause
    exit /b 1
)

echo Installing dependencies (first time downloads ~1GB, please wait)...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Dependency install failed ^(see the message above^).
    pause
    exit /b 1
)

echo(
echo Done!  Launch the app any time by double-clicking:  run.bat
pause
