@echo off
title JARVIS
cd /d "%~dp0"
where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw jarvis_app.py
) else (
    python jarvis_app.py
)
