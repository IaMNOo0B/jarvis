@echo off
title JARVIS Setup
cd /d "%~dp0"
rem Graphical installer — no terminal typing needed. Uses pythonw so no
rem console window appears; the wizard shows its own progress.
where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw setup_wizard.py
) else (
    python setup_wizard.py
)
