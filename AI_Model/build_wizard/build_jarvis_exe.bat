@echo off
title JARVIS - build the single-file JARVIS.exe
setlocal enabledelayedexpansion
cd /d "%~dp0.."

echo =============================================================
echo   JARVIS single-file build  (one double-click)
echo   Output:  dist\JARVIS\   (onedir package with JARVIS.exe)
echo   Target:  Windows, no Python needed on the machine that
echo            will run JARVIS.exe
echo =============================================================
echo.
echo [check] Python on PATH ...
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo   [!!] python.exe not on PATH.
    echo        Install Python 3.10-3.12 (64-bit) from https://python.org
    echo        and tick "Add python.exe to PATH" during install, then rerun.
    pause
    exit /b 1
)

python --version
echo.
echo [1/6] Creating isolated build environment ...
if not exist build_wizard\build_env (
    python -m venv build_wizard\build_env
    if %errorlevel% neq 0 (
        echo   [!!] venv creation failed (exit %errorlevel%).
        pause
        exit /b 1
    )
)

set "PY=build_wizard\build_env\Scripts\python.exe"
set "PIP=!PY! -m pip"
set "PYI=!PY! -m PyInstaller"

echo [2/6] Upgrading pip in build env ...
!PIP! install --upgrade pip setuptools wheel >nul 2>&1
if %errorlevel% neq 0 (
    echo   [!!] pip upgrade failed. Continue anyway.
)
echo       done.
echo [3/6] Installing build-time Python deps ...
!PIP! install pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo   [!!] pyinstaller install failed (exit %errorlevel%). Check network.
    pause
    exit /b 1
)
echo       pyinstaller installed.
echo [4/6] Installing the runtime app dependencies into the BUILD env ...
!PIP! install -r requirements.txt >nul 2>&1
echo       deps installed (warnings above are usually harmless).
echo.
echo [5/6] Running the PyInstaller build ...
echo        (onedir build; switch to --onefile in the bat for a single exe)
!PYI! --clean --noconfirm --onedir --name JARVIS Jarvis.spec
if %errorlevel% neq 0 (
    echo   [!!] PyInstaller failed (exit %errorlevel%).
    echo        Common fixes:
    echo          - install the VISUAL C++ BUILD TOOLS if 'Microsoft Visual C++' errors appear
    echo          - install torch/pytorch from https://pytorch.org if 'torch' import fails
    echo          - check the log above for "cannot find path" or "WARNING: lib not collected"
    echo          - try the onedir build first if one-file fails
    pause
    exit /b 1
)
echo       build finished.
echo [6/6] Results ...
echo        onedir package lives in: dist\JARVIS\   (copy this folder to any Windows PC)
echo.
echo        For a single-file JARVIS.exe, edit this bat and change --onedir to --onefile,
echo        then rerun.
echo.
echo =============================================================
echo   Build complete.
echo   Next: copy dist\JARVIS\ to the target machine and run JARVIS.exe.
echo   First launch downloads the offline voice/model assets (Piper +
echo   faster-whisper + openWakeWord) into %APPDATA%\JARVIS\models.
echo   Run JARVIS.exe from a folder you own (not a network share).
echo =============================================================
echo.
pause
