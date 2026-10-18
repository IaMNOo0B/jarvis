# JARVIS single-file build (PowerShell)
#   .\build_wizard\build_jarvis_exe.ps1
# Output: dist\JARVIS\  (onedir package with JARVIS.exe), or dist\JARVIS.exe (one-file if you switch the flag).
$ErrorActionPreference = "Stop"
Set-Location -Path "$PSScriptRoot\.."

# ---- helpers ----
function Msg($m) {
    Write-Host "[jarvis-build] $m" -ForegroundColor Cyan
}

# ---- 1. Python on PATH ----
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "[!!] python.exe not on PATH." -ForegroundColor Red
    Write-Host "    Install Python 3.10-3.12 (64-bit) from https://python.org"
    Write-Host "    and tick 'Add python.exe to PATH', then rerun."
    Read-Host "Press Enter to quit"
    exit 1
}
Msg ("Python " + (& python --version))

# ---- 2. venv ----
$venv = "build_wizard\build_env"
if (-not (Test-Path $venv)) {
    Msg "Creating isolated build environment ..."
    & python -m venv $venv
}

$pyExe = Join-Path $venv "Scripts\python.exe"
$pip   = "$pyExe -m pip"
$pyi   = "$pyExe -m PyInstaller"

# ---- 3. upgrade core build tools ----
Msg "Upgrading pip/setuptools/wheel in build env ..."
& $pip install --upgrade pip setuptools wheel | Out-Null

# ---- 4. PyInstaller ----
Msg "Installing PyInstaller ..."
& $pip install pyinstaller | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[!!] pyinstaller install failed (exit $LASTEXITCODE). Check network." -ForegroundColor Red
    Read-Host "Press Enter to quit"
    exit 1
}

# ---- 5. runtime deps ----
Msg "Installing runtime app dependencies into the BUILD env ..."
& $pip install -r requirements.txt | Out-Null
Msg "deps installed (warnings above are usually harmless)."

# ---- 6. build ----
Msg "Running the PyInstaller build ..."
$spec = "Jarvis.spec"
& $pyi --clean --noconfirm --onedir --name JARVIS $spec
if ($LASTEXITCODE -ne 0) {
    Write-Host "[!!] PyInstaller failed (exit $LASTEXITCODE)." -ForegroundColor Red
    Write-Host "    Common fixes:"
    Write-Host "      - install the VISUAL C++ BUILD TOOLS if 'Microsoft Visual C++' errors appear"
    Write-Host "      - install torch/pytorch from https://pytorch.org if 'torch' import fails"
    Write-Host "      - switch --onedir to --onefile for a single EXE (larger, slower startup)"
    Read-Host "Press Enter to quit"
    exit 1
}

# ---- 7. results ----
Msg "Build finished."
Msg "onedir package lives in: dist\JARVIS\   (copy this folder to any Windows PC)"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Build complete." -ForegroundColor Cyan
Write-Host "  Next: copy dist\JARVIS\ to the target machine and run JARVIS.exe." -ForegroundColor Cyan
Write-Host "  First launch downloads the offline voice/model assets (Piper +" -ForegroundColor Cyan
Write-Host "  faster-whisper + openWakeWord) into %APPDATA%\JARVIS\models." -ForegroundColor Cyan
Write-Host "  Run JARVIS.exe from a folder you own (not a network share)." -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

Write-Host ""
Write-Host "For a TRUE one-file JARVIS.exe (single exe, no folder) you must:"
Write-Host "  1. edit build_jarvis_exe.bat (or the ps1) and change --onedir to --onefile"
Write-Host "  2. rerun the build"
Write-Host "A one-file exe would land in dist\JARVIS.exe once you switch that flag."
Read-Host "Press Enter to close"
