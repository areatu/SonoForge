@echo off
setlocal enabledelayedexpansion

set APP_NAME=SonoForge
set INSTALL_DIR=%~dp0
set MENU_DIR=%ProgramData%\Microsoft\Windows\Start Menu\Programs\%APP_NAME%
if not defined LOCALAPPDATA set LOCALAPPDATA=%USERPROFILE%\AppData\Local
set DATA_DIR=%LOCALAPPDATA%\%APP_NAME%

echo.
echo ============================================
echo   %APP_NAME% Uninstaller
echo ============================================
echo.
echo   This will remove %APP_NAME% from:
echo   %INSTALL_DIR%
echo.
echo   Note: User data in %DATA_DIR% will NOT be removed.
echo.
set /p CONFIRM="Are you sure? [y/N]: "
if /i "%CONFIRM%" NEQ "y" (
    echo Cancelled.
    pause
    exit /b 0
)

echo.
echo [1/4] Removing shortcuts...
if exist "%MENU_DIR%" rmdir /s /q "%MENU_DIR%"
del "%USERPROFILE%\Desktop\%APP_NAME%.lnk" 2>nul

echo [2/4] Removing registry entries...
reg delete "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\%APP_NAME%" /f >nul 2>&1

echo [3/4] Removing application files...
cd /d "%TEMP%"
rmdir /s /q "%INSTALL_DIR%" 2>nul

echo [4/4] Done.
echo.
echo %APP_NAME% has been uninstalled.
echo User data was preserved at: %DATA_DIR%
echo   To remove user data, delete that folder manually.
echo.
pause

endlocal
