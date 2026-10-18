@echo off
title JARVIS Debug Console
cd /d "%~dp0"
echo ============================================================
echo  JARVIS debug launcher — the black window STAYS OPEN so you
echo  can see exactly what happens. If it fails, copy the red
echo  text (or the last lines) and send them to your assistant.
echo ============================================================
echo.
python jarvis_app.py
echo.
echo ------------------------------------------------------------
echo  JARVIS exited (code %errorlevel%).
echo  If the HUD never appeared, send the text above to your assistant.
echo ------------------------------------------------------------
pause
