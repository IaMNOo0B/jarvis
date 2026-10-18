@echo off
title JARVIS Setup
cd /d "%~dp0"
rem Graphical installer — no terminal typing needed. Uses pythonw so no
rem console window appears; the wizard shows its own progress.
where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw setup_wizard.py
    exit /b
)
where python >nul 2>&1
if %errorlevel%==0 (
    python setup_wizard.py
    exit /b
)
echo.
echo   JARVIS couldn't find Python, sir.
echo   Install Python 3.10-3.12 64-bit from python.org and tick
echo   "Add python.exe to PATH" during setup, then run this again.
echo.
pause
