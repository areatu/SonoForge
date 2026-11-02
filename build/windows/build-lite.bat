@echo off
setlocal enabledelayedexpansion

REM SonoForge Lightweight Windows Build
REM Assembles the lightweight ZIP package with its setup/uninstall helper scripts

set APP_NAME=SonoForge
for /f "tokens=*" %%v in ('python -c "import sys; sys.path.insert(0,'src'); from echo_personal_tool import __version__; print(__version__)"') do set APP_VERSION=%%v
set STAGE=dist\SonoForge-Setup

echo.
echo === SonoForge Lite Build v%APP_VERSION% ===
echo.

REM 1. Clean
echo [1/4] Cleaning...
if exist "%STAGE%" rmdir /s /q "%STAGE%"
if not exist "dist" mkdir "dist"

REM 2. Assemble staging directory
echo [2/4] Assembling package...
mkdir "%STAGE%\lib"
mkdir "%STAGE%\bin"

xcopy /E /I /Q "src\echo_personal_tool" "%STAGE%\lib\echo_personal_tool"
where uv >nul 2>&1
if errorlevel 1 (
    echo ERROR: uv is required to build the hash-pinned runtime requirements from uv.lock.
    echo Install uv and retry; refusing to produce an unpinned Windows package.
    exit /b 1
)
uv export --locked --no-emit-project --format requirements-txt -o "%STAGE%\lib\pinned-packages.txt"
if errorlevel 1 (
    echo ERROR: failed to export the locked requirements from uv.lock.
    exit /b 1
)
findstr /C:"--hash=sha256:" "%STAGE%\lib\pinned-packages.txt" >nul
if errorlevel 1 (
    echo ERROR: exported requirements do not contain SHA256 hashes.
    exit /b 1
)
copy /Y "build\windows\sonoforge-launcher.bat" "%STAGE%\bin\SonoForge.bat" >nul
copy /Y "scripts\setup.bat" "%STAGE%\setup.bat" >nul 2>nul
copy /Y "scripts\uninstall.bat" "%STAGE%\uninstall.bat" >nul 2>nul

REM 3. Create .zip from staging
echo [3/4] Creating archive...
set ZIP_NAME=%APP_NAME%-%APP_VERSION%-Windows.zip
powershell -Command "Compress-Archive -Path '%STAGE%\*' -DestinationPath 'dist\%ZIP_NAME%' -Force"

REM 4. Done
echo.
echo [4/4] Done!
echo.
echo   Staging:  %STAGE%
echo   Archive:  dist\%ZIP_NAME%
echo.

endlocal
