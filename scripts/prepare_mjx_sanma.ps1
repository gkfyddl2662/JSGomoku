param(
    [string]$Destination = "C:\Mortal_ROGS\mjx-sanma",
    [string]$Ref = "v0.1.0"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Manifest = Join-Path $ProjectRoot "mjx_sanma\manifest.toml"
$Audit = Join-Path $PSScriptRoot "audit_mjx_sanma.py"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "git is required"
}

if (-not (Test-Path $Destination)) {
    New-Item -ItemType Directory -Path (Split-Path -Parent $Destination) -Force | Out-Null
    git clone https://github.com/mjx-project/mjx $Destination
}

Push-Location $Destination
try {
    git fetch --tags --force origin
    git checkout --force $Ref
    git submodule update --init --recursive
} finally {
    Pop-Location
}

$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) {
    throw "python is required to run the MJX source audit"
}

& $Python.Source $Audit --root $Destination --manifest $Manifest --allow-blockers
if ($LASTEXITCODE -ne 0) {
    throw "Pinned MJX source audit failed with exit code $LASTEXITCODE"
}

Write-Host "MJX Sanma source is pinned and ready for staged patching: $Destination"
Write-Host "4P blockers are expected until all sanma patch stages are applied."
