@echo off
setlocal enabledelayedexpansion

set APP_NAME=SonoForge
set DEFAULT_DIR=%ProgramFiles%\%APP_NAME%
set MENU_DIR=%ProgramData%\Microsoft\Windows\Start Menu\Programs\%APP_NAME%

echo.
echo     ___  ___  ________  _________
echo    /   ^|/  / / ____/ / / / ____/
echo   / / ^|   / / __/ / / / / __
echo  / ___   / /_/ / /_/ / /_/ /
echo /_/  ^|_/____/\____/\____/
echo.
echo   Echocardiography Analysis Platform
echo ============================================
echo.
echo   This will install %APP_NAME% to:
echo   %DEFAULT_DIR%
echo.
set /p INSTALL_DIR="Install directory [%DEFAULT_DIR%]: "
if "%INSTALL_DIR%"=="" set INSTALL_DIR=%DEFAULT_DIR%

echo.
echo [1/4] Installing files...
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
xcopy /E /I /Q /Y "%~dp0lib" "%INSTALL_DIR%\lib" >nul
copy /Y "%~dp0uninstall.bat" "%INSTALL_DIR%\uninstall.bat" >nul

REM Copy launcher: prefer .exe (PyInstaller), fallback to .bat (lite)
set "LAUNCHER_EXE=%~dp0SonoForge.exe"
set "LAUNCHER_BAT=%~dp0bin\SonoForge.bat"
if exist "%LAUNCHER_EXE%" (
    copy /Y "%LAUNCHER_EXE%" "%INSTALL_DIR%\SonoForge.exe" >nul
    set "LAUNCH_TARGET=%INSTALL_DIR%\SonoForge.exe"
) else if exist "%LAUNCHER_BAT%" (
    if not exist "%INSTALL_DIR%\bin" mkdir "%INSTALL_DIR%\bin"
    xcopy /E /I /Q /Y "%~dp0bin" "%INSTALL_DIR%\bin" >nul
    set "LAUNCH_TARGET=%INSTALL_DIR%\bin\SonoForge.bat"
) else (
    echo [ERROR] No launcher found (SonoForge.exe or bin\SonoForge.bat^).
    pause
    exit /b 1
)

echo [2/4] Creating Start Menu shortcuts...
if not exist "%MENU_DIR%" mkdir "%MENU_DIR%"

REM Create shortcut via PowerShell
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%MENU_DIR%\%APP_NAME%.lnk'); $s.TargetPath = '!LAUNCH_TARGET!'; $s.WorkingDirectory = '%INSTALL_DIR%'; $s.Description = '%APP_NAME% - Echocardiography Analysis'; $s.Save()"

powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%MENU_DIR%\Uninstall %APP_NAME%.lnk'); $s.TargetPath = '%INSTALL_DIR%\uninstall.bat'; $s.WorkingDirectory = '%INSTALL_DIR%'; $s.Description = 'Uninstall %APP_NAME%'; $s.Save()"

echo [3/4] Creating desktop shortcut...
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut([System.IO.Path]::Combine([System.Environment]::GetFolderPath('Desktop'), '%APP_NAME%.lnk')); $s.TargetPath = '!LAUNCH_TARGET!'; $s.WorkingDirectory = '%INSTALL_DIR%'; $s.Description = '%APP_NAME% - Echocardiography Analysis'; $s.Save()"

echo [4/4] Registering uninstaller...
reg add "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\%APP_NAME%" /v "DisplayName" /t REG_SZ /d "%APP_NAME%" /f >nul 2>&1
reg add "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\%APP_NAME%" /v "UninstallString" /t REG_SZ /d "\"%INSTALL_DIR%\uninstall.bat\"" /f >nul 2>&1
reg add "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\%APP_NAME%" /v "InstallLocation" /t REG_SZ /d "%INSTALL_DIR%" /f >nul 2>&1
for /f "tokens=*" %%v in ('python -c "import sys; sys.path.insert(0,'%~dp0lib'); from echo_personal_tool import __version__; print(__version__)"') do set REG_VER=%%v
reg add "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\%APP_NAME%" /v "DisplayVersion" /t REG_SZ /d "%REG_VER%" /f >nul 2>&1
reg add "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\%APP_NAME%" /v "Publisher" /t REG_SZ /d "SonoForge" /f >nul 2>&1

echo.
echo ============================================
echo   Installation complete!
echo ============================================
echo.
echo   Install location: %INSTALL_DIR%
echo   Start Menu:       %MENU_DIR%
echo.
set /p LAUNCH="Launch %APP_NAME% now? [Y/n]: "
if /i "%LAUNCH%" NEQ "n" (
    echo Starting %APP_NAME%...
    start "" "!LAUNCH_TARGET!"
)

endlocal
