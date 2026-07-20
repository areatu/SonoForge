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
    echo.
    echo [SonoForge] Python 3.10+ is required but not found.
    echo.
    echo Options:
    echo   1. Download Python from python.org (recommended)
    echo   2. Try winget install (if available)
    echo   3. Exit
    echo.
    set /p CHOICE="Select [1/2/3]: "

    if "!CHOICE!"=="1" (
        echo Opening Python download page...
        start https://www.python.org/downloads/
        echo.
        echo After installing Python, make sure to:
        echo   - Check "Add Python to PATH" during installation
        echo   - Restart this launcher
        pause
        exit /b 1
    ) else if "!CHOICE!"=="2" (
        echo Trying winget install...
        winget install Python.Python.3.11 --accept-package-agreements --accept-source-agreements
        if %errorlevel%==0 (
            echo Python installed. Please restart this launcher.
            pause
            exit /b 1
        ) else (
            echo winget install failed. Please install Python manually.
            pause
            exit /b 1
        )
    ) else (
        exit /b 1
    )
)

REM ── Check Python version ──
for /f "tokens=2 delims=." %%a in ('%PYTHON% --version 2^>^&1') do set PYMAJOR=%%a
for /f "tokens=3 delims=." %%a in ('%PYTHON% --version 2^>^&1') do set PYMINOR=%%a

if %PYMAJOR% LSS 3 (
    echo [SonoForge] ERROR: Python 3.10+ required, found Python %PYMAJOR%.%PYMINOR%
    pause
    exit /b 1
)
if %PYMINOR% LSS 10 (
    echo [SonoForge] ERROR: Python 3.10+ required, found Python %PYMAJOR%.%PYMINOR%
    pause
    exit /b 1
)

echo [SonoForge] Using: %PYTHON% (Python %PYMAJOR%.%PYMINOR%)

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

REM ── 4. Download models (optional) ──
if not exist "%MODELS_DIR%\model_manifest.json" (
    echo.
    echo [SonoForge] AI models are required for automatic cardiac segmentation.
    echo [SonoForge] Download size: ~300 MB
    echo.
    set /p DOWNLOAD_MODELS="Download models? [Y/n]: "

    if /i "!DOWNLOAD_MODELS!" NEQ "n" (
        echo [SonoForge] Downloading models...
        if not exist "%MODELS_DIR%" mkdir "%MODELS_DIR%"

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
            echo [SonoForge] Model download failed. AI segmentation will be unavailable.
            echo [SonoForge] Download manually: %MODELS_URL%
        )
    ) else (
        echo [SonoForge] Skipping models. AI segmentation will be unavailable.
        echo [SonoForge] You can download later from: %MODELS_URL%
    )
) else (
    echo [SonoForge] Models found.
)

REM ── 5. Launch ──
echo [SonoForge] Starting SonoForge...
set PYTHONPATH=%LIB_DIR%;%PYTHONPATH%
"%VENV_PYTHON%" -m echo_personal_tool %*

endlocal
