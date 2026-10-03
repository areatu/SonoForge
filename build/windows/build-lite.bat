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
copy /Y "pyproject.toml" "%STAGE%\lib\" >nul
if exist "uv.lock" copy /Y "uv.lock" "%STAGE%\lib\" >nul
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
