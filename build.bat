@echo off
setlocal
cd /d "%~dp0"

set "VENV_PY=.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo(
    echo .venv not found. Run setup.bat first, then build.bat.
    echo(
    pause
    exit /b 1
)

echo Ensuring PyInstaller is installed...
"%VENV_PY%" -m pip install pyinstaller

echo(
echo Building Rekounts.exe (onedir). This takes a couple of minutes...
"%VENV_PY%" -m PyInstaller --noconfirm --clean Rekounts.spec
if errorlevel 1 (
    echo(
    echo Build failed - see the output above.
    pause
    exit /b 1
)

echo(
echo Done!  The app is at:  dist\Rekounts\Rekounts.exe
echo Zip the whole "dist\Rekounts" folder to share it.
echo Note: the .exe is unsigned, so Windows SmartScreen may warn on first run
echo       (More info ^> Run anyway). See the README for details.
echo(
pause
