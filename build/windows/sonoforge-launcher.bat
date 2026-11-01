@echo off
setlocal enabledelayedexpansion

REM ============================================
REM  SonoForge Launcher (Windows)
REM  Checks environment, installs deps/models if needed, then launches.
REM ============================================

set APP_NAME=SonoForge
set "LIB_DIR=%~dp0..\lib"
if not exist "%LIB_DIR%\echo_personal_tool" set "LIB_DIR=%~dp0lib"
if not exist "%LIB_DIR%\echo_personal_tool" set "LIB_DIR=%~dp0..\..\src"
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
    echo [SonoForge] Python 3.11-3.13 is required but not found.
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

REM ── Check Python version (mirrors requires-python in pyproject.toml: >=3.11,<3.14) ──
for /f "tokens=2" %%a in ('%PYTHON% --version 2^>^&1') do set PYFULL=%%a
for /f "tokens=1,2 delims=." %%a in ("%PYFULL%") do (
    set PYMAJOR=%%a
    set PYMINOR=%%b
)

if %PYMAJOR% LSS 3 (
    echo [SonoForge] ERROR: Python 3.11-3.13 required (3.11 ^<= version ^< 3.14), found Python %PYMAJOR%.%PYMINOR%
    pause
    exit /b 1
)
if %PYMINOR% LSS 11 (
    echo [SonoForge] ERROR: Python 3.11-3.13 required (3.11 ^<= version ^< 3.14), found Python %PYMAJOR%.%PYMINOR%
    pause
    exit /b 1
)
if %PYMINOR% GEQ 14 (
    echo [SonoForge] ERROR: Python 3.11-3.13 required (3.11 ^<= version ^< 3.14), found Python %PYMAJOR%.%PYMINOR%
    pause
    exit /b 1
)

echo [SonoForge] Using: %PYTHON% (Python %PYMAJOR%.%PYMINOR%)

REM Resolve paths and migrate with the same module used by the application.
set "PYTHONPATH=%LIB_DIR%;%PYTHONPATH%"
for /f "delims=" %%P in ('%PYTHON% -m echo_personal_tool.infrastructure.paths --print-data-dir') do set "DATA_DIR=%%P"
if "%DATA_DIR%"=="" (
    if defined LOCALAPPDATA (set "DATA_DIR=%LOCALAPPDATA%\SonoForge") else set "DATA_DIR=%USERPROFILE%\AppData\Local\SonoForge"
)
for /f "delims=" %%P in ('%PYTHON% -m echo_personal_tool.infrastructure.paths --print-models-dir') do set "MODELS_DIR=%%P"
if "%MODELS_DIR%"=="" set "MODELS_DIR=%DATA_DIR%\models"
%PYTHON% -m echo_personal_tool.infrastructure.paths --migrate
if errorlevel 1 echo [SonoForge] Legacy data migration will be retried when the app starts.
for /f "delims=" %%P in ('%PYTHON% -m echo_personal_tool.infrastructure.paths --print-models-read-dir') do set "MODELS_READ_DIR=%%P"
if "%MODELS_READ_DIR%"=="" set "MODELS_READ_DIR=%MODELS_DIR%"
set "VENV_DIR=%DATA_DIR%\venv"

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
    set "PINS_FILE=%LIB_DIR%\pinned-packages.txt"
    if not exist "!PINS_FILE!" (
        echo [SonoForge] ERROR: hash-pinned requirements are missing. Rebuild from the official package.
        exit /b 1
    )
    findstr /C:"--hash=sha256:" "!PINS_FILE!" >nul
    if errorlevel 1 (
        echo [SonoForge] ERROR: pinned requirements do not contain hashes; refusing installation.
        exit /b 1
    )
    if not defined SONOFORGE_INSTALL_MODE set "SONOFORGE_INSTALL_MODE=online"
    if /i "!SONOFORGE_INSTALL_MODE!"=="online" (
        echo [SonoForge] Online mode: installing lock-pinned dependencies with SHA256 verification.
        "%VENV_PIP%" install --quiet --require-hashes -r "!PINS_FILE!"
        if errorlevel 1 goto :dependency_install_failed
    ) else if /i "!SONOFORGE_INSTALL_MODE!"=="offline" (
        if not defined SONOFORGE_WHEELHOUSE (
            echo [SonoForge] ERROR: offline mode requires SONOFORGE_WHEELHOUSE to name a wheelhouse directory.
            exit /b 1
        )
        if not exist "%SONOFORGE_WHEELHOUSE%\" (
            echo [SonoForge] ERROR: wheelhouse directory not found: %SONOFORGE_WHEELHOUSE%
            exit /b 1
        )
        echo [SonoForge] Offline mode: installing only from %SONOFORGE_WHEELHOUSE%.
        "%VENV_PIP%" install --quiet --no-index --find-links "%SONOFORGE_WHEELHOUSE%" --require-hashes -r "!PINS_FILE!"
        if errorlevel 1 goto :dependency_install_failed
    ) else (
        echo [SonoForge] ERROR: SONOFORGE_INSTALL_MODE must be online or offline.
        exit /b 1
    )
    echo. > "%MARKER%"
    echo [SonoForge] Dependencies installed.
) else (
    echo [SonoForge] Dependencies up to date.
)

REM ── 4. Download models (optional) ──
if not exist "%MODELS_READ_DIR%\model_manifest.json" (
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
            echo [SonoForge] Verifying model archive SHA256...
            "%PYTHON%" -m echo_personal_tool.infrastructure.runtime_setup --verify-models-archive "%DATA_DIR%\models.tar.gz"
            if errorlevel 1 (
                echo [SonoForge] ERROR: archive checksum mismatch; refusing to extract models.
                del "%DATA_DIR%\models.tar.gz"
                exit /b 1
            )
            echo [SonoForge] Extracting verified models...
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
set "APP_EXIT=%ERRORLEVEL%"
endlocal & exit /b %APP_EXIT%

:dependency_install_failed
echo [SonoForge] ERROR: dependency installation failed; no unpinned fallback was attempted.
echo [SonoForge] Online mode requires network access. Offline mode uses a local wheelhouse.
exit /b 1
