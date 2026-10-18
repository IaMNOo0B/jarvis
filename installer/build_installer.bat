@echo off
title JARVIS - build the installer
setlocal
cd /d "%~dp0.."

echo ============================================================
echo   JARVIS installer build
echo   1. freezes the app  (dist\JARVIS\JARVIS.exe)
echo   2. compiles the installer  (JARVIS_Setup.exe)
echo ============================================================
echo.

if not exist "AI_Model\build_wizard\build_jarvis_exe.bat" (
    echo [!!] build wizard not found.
    pause
    exit /b 1
)

echo [1/2] Freezing the app ...
call "AI_Model\build_wizard\build_jarvis_exe.bat"
if errorlevel 1 (
    echo [!!] Freeze failed - see messages above.
    pause
    exit /b 1
)

echo.
echo [2/2] Compiling the installer ...
set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo [!!] Inno Setup 6 not found.
    echo      Install it free from https://jrsoftware.org/isinfo.php
    echo      then run this again.
    pause
    exit /b 1
)
"%ISCC%" "installer\JARVIS.iss"
if errorlevel 1 (
    echo [!!] Installer compile failed.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Done:  JARVIS_Setup.exe
echo   Share it or run it - no Python needed on the target PC.
echo ============================================================
pause
