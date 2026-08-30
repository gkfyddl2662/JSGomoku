param(
    [string]$RuntimeRoot = "$PSScriptRoot\..\..\Mortal_ROGS_Runtime",
    [string]$Legacy3PRoot = "$PSScriptRoot\..\..\Mortal_Sanma",
    [switch]$InstallRustIfMissing,
    [switch]$Bootstrap4P,
    [switch]$SkipSmoke
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
$RuntimeRoot = [System.IO.Path]::GetFullPath($RuntimeRoot)
$Legacy3PRoot = [System.IO.Path]::GetFullPath($Legacy3PRoot)
$Dest3P = Join-Path $RuntimeRoot "3p"
$Dest4P = Join-Path $RuntimeRoot "4p"
$Bootstrap = Join-Path $ProjectRoot "scripts\bootstrap_runtime.ps1"
$Smoke = Join-Path $ProjectRoot "scripts\smoke_windows.ps1"

New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null

if (-not (Test-Path $Dest3P)) {
    if (-not (Test-Path $Legacy3PRoot)) {
        throw "Neither unified 3P runtime nor legacy 3P runtime exists: $Legacy3PRoot"
    }
    Write-Host "Moving existing 3P runtime into unified root..." -ForegroundColor Cyan
    Move-Item -LiteralPath $Legacy3PRoot -Destination $Dest3P
} elseif (Test-Path $Legacy3PRoot) {
    Write-Host "Unified 3P runtime already exists; legacy directory left untouched: $Legacy3PRoot" -ForegroundColor Yellow
}

$train = Join-Path $Dest3P "Mortal\mortal\train.py"
if (-not (Test-Path $train -PathType Leaf)) {
    throw "Moved 3P runtime is incomplete: $train"
}
$patched = Select-String -Path $train -Pattern "compute_mortal_rogs_batch" -Quiet

$args = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $Bootstrap,
    "-Mode", "3p",
    "-InstallRoot", $Dest3P
)
if ($InstallRustIfMissing) { $args += "-InstallRustIfMissing" }
if ($patched) {
    Write-Host "Existing RTX/ROGS patch detected; preserving patched source." -ForegroundColor Green
    $args += "-SkipPatch"
}

# Recreate the Python environment inside 3p/.venv. A virtualenv is not moved
# from the project root because Windows venv launchers can contain absolute paths.
Write-Host "Rebuilding isolated 3P venv at $Dest3P\.venv..." -ForegroundColor Cyan
& powershell.exe @args
if ($LASTEXITCODE -ne 0) {
    throw "3P unified-runtime migration bootstrap failed with exit code $LASTEXITCODE"
}

if ($Bootstrap4P) {
    Write-Host ""
    Write-Host "Bootstrapping 4P beside 3P..." -ForegroundColor Cyan
    $args4 = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $Bootstrap,
        "-Mode", "4p",
        "-InstallRoot", $Dest4P
    )
    if ($InstallRustIfMissing) { $args4 += "-InstallRustIfMissing" }
    & powershell.exe @args4
    if ($LASTEXITCODE -ne 0) {
        throw "4P unified-runtime bootstrap failed with exit code $LASTEXITCODE"
    }
}

Write-Host ""
Write-Host "UNIFIED_RUNTIME_MIGRATION_OK root=$RuntimeRoot" -ForegroundColor Green
Write-Host "3P: $Dest3P"
Write-Host "4P: $Dest4P"
Write-Host "Legacy project .venv was intentionally left untouched and can be removed later after smoke validation."

if (-not $SkipSmoke -and (Test-Path "$Dest4P\.venv\Scripts\python.exe")) {
    Write-Host ""
    Write-Host "Running unified runtime smoke..." -ForegroundColor Cyan
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Smoke -RuntimeRoot $RuntimeRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Unified runtime smoke failed with exit code $LASTEXITCODE"
    }
}
