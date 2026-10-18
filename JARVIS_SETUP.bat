@echo off
title JARVIS Setup
cd /d "%~dp0"
echo ==================================================
echo   JARVIS setup  (one time only)
echo ==================================================
echo.
echo [1/3] Checking dependencies, voice and models...
echo.
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found on PATH.
    echo         Install Python 3.11+ from https://python.org and tick
    echo         "Add python.exe to PATH" during install.
    pause
    exit /b 1
)

echo.
echo [1/3] Checking dependencies, voice and models...
python setup_models.py
if errorlevel 1 (
    echo [ERROR] Setup failed - read the messages above.
    pause
    exit /b 1
)

echo.
echo [2/3] Gemini online brain
echo        Get a FREE key at https://aistudio.google.com/apikey
set "GEMKEY="
set /p GEMKEY=Paste your Gemini key then Enter (or just Enter to skip): 
if defined GEMKEY (
    python set_cloud_key.py "%GEMKEY%"
) else (
    echo        Skipped - JARVIS runs local-only for now.
echo        Add it later with:  python set_cloud_key.py YOUR_KEY
)

echo.
echo [3/3] Verifying everything...
python test_dual_brain.py

echo.
echo ==================================================
echo   Setup finished.
echo   Start JARVIS with:   JARVIS_START.bat
echo   or double-click the JARVIS icon on your Desktop.
echo   Quit JARVIS anytime with:  Ctrl+Alt+Q
echo ==================================================
pause
