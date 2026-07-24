@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem  Builds everything a release needs, in one run:
rem
rem    dist\Rekounts\Rekounts.exe          the app (PyInstaller onedir)
rem    dist\Rekounts-<version>-win64.zip   the portable download
rem    dist\Rekounts-Setup-<version>.exe   the installer
rem
rem  The installer step needs Inno Setup 6.3+ (winget install JRSoftware.InnoSetup).
rem  Without it the first two still get built and this says so, rather than
rem  failing a build that is perfectly usable — see CONTRIBUTING.md.
rem
rem  Pass  --no-installer  to stop after the ZIP.

set "VENV_PY=.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo(
    echo .venv not found. Run setup.bat first, then build.bat.
    echo(
    pause
    exit /b 1
)

for /f "usebackq delims=" %%v in (`"%VENV_PY%" scripts\version.py`) do set "VERSION=%%v"
if not defined VERSION (
    echo(
    echo Could not read the version from rekounts\__init__.py.
    pause
    exit /b 1
)
echo Building Rekounts %VERSION%

rem --- 1: the app --------------------------------------------------------------
echo(
echo [1/3] Ensuring PyInstaller is installed...
"%VENV_PY%" -m pip install pyinstaller

echo(
echo [1/3] Building Rekounts.exe (onedir). This takes a couple of minutes...
"%VENV_PY%" -m PyInstaller --noconfirm --clean Rekounts.spec
if errorlevel 1 (
    echo(
    echo Build failed - see the output above.
    pause
    exit /b 1
)

rem --- 2: the portable ZIP -----------------------------------------------------
set "ZIP=dist\Rekounts-%VERSION%-win64.zip"
echo(
echo [2/3] Packing %ZIP% ...
if exist "%ZIP%" del "%ZIP%"
rem  Compress-Archive on the FOLDER, not its contents, so the zip unpacks into a
rem  "Rekounts" folder instead of spraying ~400 files into the user's Downloads.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "Compress-Archive -Path 'dist\Rekounts' -DestinationPath '%ZIP%' -CompressionLevel Optimal -Force"
if errorlevel 1 (
    echo(
    echo Could not create the ZIP - see the output above.
    pause
    exit /b 1
)

rem --- 3: the installer --------------------------------------------------------
if /i "%~1"=="--no-installer" (
    echo(
    echo [3/3] Skipped (--no-installer^).
    goto :summary
)

set "ISCC="
for %%p in (
    "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
    "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
    "%ProgramFiles%\Inno Setup 6\ISCC.exe"
) do if not defined ISCC if exist %%p set "ISCC=%%~p"

if not defined ISCC (
    echo(
    echo [3/3] Inno Setup not found - skipping the installer.
    echo       Install it with:  winget install -e --id JRSoftware.InnoSetup
    echo       then re-run build.bat. The app and the ZIP above are already built.
    goto :summary
)

echo(
echo [3/3] Compiling the installer with "%ISCC%" ...
"%ISCC%" /Q installer\rekounts.iss
if errorlevel 1 (
    echo(
    echo The installer failed to compile - see the output above.
    pause
    exit /b 1
)
set "SETUP=dist\Rekounts-Setup-%VERSION%.exe"

:summary
echo(
echo Done. In dist\:
echo(
echo   Rekounts\Rekounts.exe                 the app
echo   Rekounts-%VERSION%-win64.zip          portable download (unzip and run^)
if defined SETUP echo   Rekounts-Setup-%VERSION%.exe          installer (per-user, no admin^)
echo(
echo Note: nothing here is code-signed, so Windows SmartScreen may warn on first
echo       run (More info ^> Run anyway^). See the README for details.
echo(
pause
