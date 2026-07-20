@echo off
setlocal enabledelayedexpansion

REM ============================================
REM  SonoForge Launcher (Windows)
REM  Checks environment, installs deps/models if needed, then launches.
REM ============================================

set APP_NAME=SonoForge
set DATA_DIR=%USERPROFILE%\.local\share\sonoforge
set VENV_DIR=%DATA_DIR%\venv
set MODELS_DIR=%DATA_DIR%\models
set LIB_DIR=%~dp0lib
set MODELS_URL=https://github.com/areatu/sonoforge-models/releases/download/models-v1/models-v1.tar.gz

echo [SonoForge] Checking environment...

REM ── 1. Find Python ──
set PYTHON=
where python >nul 2>&1
if %errorlevel%==0 (
    for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
    set PYTHON=python
) else (
    where python3 >nul 2>&1
    if %errorlevel%==0 (
        set PYTHON=python3
    )
)

if "%PYTHON%"=="" (
    echo [SonoForge] ERROR: Python 3.10+ not found.
    echo Install: https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

echo [SonoForge] Using: %PYTHON%

REM ── 2. Create venv if missing ──
if not exist "%VENV_DIR%" (
    echo [SonoForge] Creating virtual environment...
    if not exist "%DATA_DIR%" mkdir "%DATA_DIR%"
    %PYTHON% -m venv "%VENV_DIR%"
    echo [SonoForge] venv created.
)

set VENV_PYTHON=%VENV_DIR%\Scripts\python.exe
set VENV_PIP=%VENV_DIR%\Scripts\pip.exe

REM ── 3. Install dependencies ──
set MARKER=%VENV_DIR%\.deps_installed
set NEED_INSTALL=0
if not exist "%MARKER%" set NEED_INSTALL=1

if "%NEED_INSTALL%"=="1" (
    echo [SonoForge] Installing dependencies (this may take a few minutes)...
    "%VENV_PIP%" install --quiet --upgrade pip
    "%VENV_PIP%" install --quiet ^
        PySide6 pyqtgraph pydicom pylibjpeg pylibjpeg-openjpeg pylibjpeg-libjpeg ^
        "numpy<2" scipy opencv-python-headless httpx psutil pymupdf pynetdicom ^
        pyyaml jsonschema onnxruntime reportlab openpyxl keyring
    echo. > "%MARKER%"
    echo [SonoForge] Dependencies installed.
) else (
    echo [SonoForge] Dependencies up to date.
)

REM ── 4. Download models if missing ──
if not exist "%MODELS_DIR%\model_manifest.json" (
    echo [SonoForge] Downloading models (~300 MB)...
    if not exist "%MODELS_DIR%" mkdir "%MODELS_DIR%"

    REM Try curl first, then PowerShell
    where curl >nul 2>&1
    if %errorlevel%==0 (
        curl -fSL --connect-timeout 30 --retry 2 --progress-bar -o "%DATA_DIR%\models.tar.gz" "%MODELS_URL%"
    ) else (
        powershell -Command "Invoke-WebRequest -Uri '%MODELS_URL%' -OutFile '%DATA_DIR%\models.tar.gz'"
    )

    if exist "%DATA_DIR%\models.tar.gz" (
        echo [SonoForge] Extracting models...
        tar -xzf "%DATA_DIR%\models.tar.gz" -C "%DATA_DIR%"
        del "%DATA_DIR%\models.tar.gz"
    )

    if exist "%MODELS_DIR%\model_manifest.json" (
        echo [SonoForge] Models ready.
    ) else (
        echo [SonoForge] Model download failed. Models will be unavailable.
        echo [SonoForge] Download manually: %MODELS_URL%
    )
) else (
    echo [SonoForge] Models found.
)

REM ── 5. Launch ──
echo [SonoForge] Starting SonoForge...
set PYTHONPATH=%LIB_DIR%;%PYTHONPATH%
"%VENV_PYTHON%" -m echo_personal_tool %*

endlocal
