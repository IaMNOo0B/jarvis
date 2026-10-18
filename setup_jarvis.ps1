# JARVIS one-shot setup (PowerShell wrapper)
#   .\setup_jarvis.ps1
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
Write-Host "== JARVIS setup ==" -ForegroundColor Cyan
python -m pip install --upgrade pip
python setup_models.py
Write-Host ""
Write-Host "Done. Start JARVIS with:  python jarvis_app.py" -ForegroundColor Green
