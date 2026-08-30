param(
    [string]$MortalRoot = "C:\Mortal_Sanma"
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root

if (-not (Test-Path "$Root\.venv\Scripts\python.exe") -or -not (Test-Path "$MortalRoot\Mortal\mortal\train.py")) {
    Write-Host "First run detected. Running bootstrap..."
    & "$Root\scripts\bootstrap.ps1" -InstallRoot $MortalRoot
}

$env:MORTAL_SANMA_ROOT = $MortalRoot
$env:MORTAL_WEBUI_HOST = "127.0.0.1"
$env:MORTAL_WEBUI_PORT = "8188"

Start-Process "http://127.0.0.1:8188"
& "$Root\.venv\Scripts\python.exe" -m app.main
