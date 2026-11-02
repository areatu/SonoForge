@echo off
setlocal

REM SonoForge Windows package build. Run from the repository root.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.11 and add it to PATH.
    exit /b 1
)

for /f "tokens=*" %%v in ('python -c "import sys; sys.path.insert(0,'src'); from echo_personal_tool import __version__; print(__version__)"') do set "APP_VERSION=%%v"
if not defined APP_VERSION (
    echo [ERROR] Could not determine the SonoForge version.
    exit /b 1
)

echo.
echo === SonoForge Windows build %APP_VERSION% ===
echo.

echo [1/4] Installing build dependencies...
python -m pip install -e .
if errorlevel 1 exit /b 1
python -m pip install pyinstaller
if errorlevel 1 exit /b 1

echo [2/4] Building the portable one-file executable...
python -m PyInstaller sonoforge-standalone.spec --noconfirm --clean
if errorlevel 1 exit /b 1
copy /Y "dist\SonoForge.exe" "dist\SonoForge-%APP_VERSION%-portable.exe" >nul
if errorlevel 1 exit /b 1

echo [3/4] Building the installer onedir payload...
python -m PyInstaller build\windows\build.spec --noconfirm --clean
if errorlevel 1 exit /b 1

set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC="
if not defined ISCC for /f "delims=" %%i in ('where ISCC.exe 2^>nul') do set "ISCC=%%i"
if defined ISCC (
    echo [4/4] Compiling the setup installer...
    call "%ISCC%" /DMyAppVersion=%APP_VERSION% build\windows\sonoforge.iss
    if errorlevel 1 exit /b 1
) else (
    echo [4/4] ISCC not found; installer compilation skipped.
    echo Install Inno Setup 6 and rerun this script to create the setup EXE.
)

echo.
echo Build complete:
echo   Portable: dist\SonoForge-%APP_VERSION%-portable.exe
echo   Onedir:   dist\SonoForge\
if defined ISCC echo   Setup:    dist\SonoForge-Setup-%APP_VERSION%-x64.exe
echo.

endlocal
