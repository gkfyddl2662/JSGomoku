param(
    [string]$RuntimeRoot = "$PSScriptRoot\..\..\Mortal_ROGS_Runtime",
    [switch]$SkipRustBuild,
    [switch]$InstallRustIfMissing,
    [switch]$SkipSmoke
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
$RuntimeRoot = [System.IO.Path]::GetFullPath($RuntimeRoot)
$Bootstrap = Join-Path $ProjectRoot "scripts\bootstrap_runtime.ps1"
$Smoke = Join-Path $ProjectRoot "scripts\smoke_windows.ps1"

New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null

function Invoke-ModeBootstrap([string]$Mode) {
    $root = Join-Path $RuntimeRoot $Mode
    $args = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $Bootstrap,
        "-Mode", $Mode,
        "-InstallRoot", $root
    )
    if ($SkipRustBuild) { $args += "-SkipRustBuild" }
    if ($InstallRustIfMissing) { $args += "-InstallRustIfMissing" }

    Write-Host ""
    Write-Host "=== Bootstrapping Mortal $Mode at $root ===" -ForegroundColor Cyan
    & powershell.exe @args
    if ($LASTEXITCODE -ne 0) {
        throw "$Mode bootstrap failed with exit code $LASTEXITCODE"
    }
}

Invoke-ModeBootstrap "3p"
Invoke-ModeBootstrap "4p"

Write-Host ""
Write-Host "UNIFIED_RUNTIME_BOOTSTRAP_OK root=$RuntimeRoot" -ForegroundColor Green
Write-Host "3P: $(Join-Path $RuntimeRoot '3p')"
Write-Host "4P: $(Join-Path $RuntimeRoot '4p')"

if (-not $SkipSmoke) {
    Write-Host ""
    Write-Host "=== Running unified dual-runtime smoke ===" -ForegroundColor Cyan
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Smoke -RuntimeRoot $RuntimeRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Unified runtime smoke failed with exit code $LASTEXITCODE"
    }
}
