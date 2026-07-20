@echo off
setlocal enabledelayedexpansion

REM ============================================
REM  SonoForge — Lightweight Windows Build
REM  Packages app code only (~50MB).
REM  Dependencies + models are downloaded at first run.
REM ============================================

set APP_NAME=SonoForge
for /f "tokens=2" %%v in ('python -c "import sys; sys.path.insert(0,'src'); from echo_personal_tool import __version__; print(__version__)"') do set APP_VERSION=%%v
set BUILD_DIR=build\dist-lite
set DIST_DIR=dist
set SRC_DIR=src\echo_personal_tool

echo.
echo === SonoForge Lite Build v%APP_VERSION% ===
echo.

REM ── 1. Clean ──
echo [1/5] Cleaning...
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"

REM ── 2. Assemble package ──
echo [2/5] Assembling package...
set PKG=%BUILD_DIR%\%APP_NAME%
mkdir "%PKG%\lib"
mkdir "%PKG%\bin"

REM Copy app code
xcopy /E /I /Q "src\echo_personal_tool" "%PKG%\lib\echo_personal_tool"

REM Copy project files
copy /Y "pyproject.toml" "%PKG%\lib\" >nul
if exist "uv.lock" copy /Y "uv.lock" "%PKG%\lib\" >nul

REM Copy launcher
copy /Y "build\windows\sonoforge-launcher.bat" "%PKG%\bin\SonoForge.bat" >nul

REM ── 3. Create .zip ──
echo [3/5] Creating archive...
if not exist "%DIST_DIR%" mkdir "%DIST_DIR%"
powershell -Command "Compress-Archive -Path '%PKG%\*' -DestinationPath '%DIST_DIR%\%APP_NAME%-%APP_VERSION%-Windows.zip" -Force

REM ── 4. Done ──
echo.
echo [4/5] Done!
echo.
echo   Package: %DIST_DIR%\%APP_NAME%-%APP_VERSION%-Windows.zip
echo   Size:
powershell -Command "(Get-Item '%DIST_DIR%\%APP_NAME%-%APP_VERSION%-Windows.zip').Length / 1MB" 2>nul
echo   MB
echo.
echo   Install: Extract the .zip anywhere
echo   Run:     SonoForge\bin\SonoForge.bat
echo.
echo   First run will download:
echo     - Python dependencies (~940 MB)
echo     - AI models (~300 MB)
echo.

endlocal
