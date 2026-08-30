param(
    [string]$InstallRoot = "",
    [switch]$SkipCompile,
    [switch]$SkipTrainingStep,
    [switch]$SkipControlCenter
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
    $InstallRoot = Join-Path (Split-Path $ProjectRoot -Parent) "Mortal_Unified"
}
$InstallRoot = [System.IO.Path]::GetFullPath($InstallRoot)

$Bootstrap = Join-Path $PSScriptRoot "bootstrap_unified_runtime.ps1"
$Smoke = Join-Path $PSScriptRoot "smoke_unified_windows.ps1"
foreach ($path in @($Bootstrap, $Smoke)) {
    if (-not (Test-Path $path)) {
        throw "Required unified runtime script is missing: $path"
    }
}

Write-Host "=== Mortal-ROGS unified Windows setup ==="
Write-Host "Runtime root: $InstallRoot"
Write-Host ""

& powershell.exe `
    -NoProfile `
    -ExecutionPolicy Bypass `
    -File $Bootstrap `
    -InstallRoot $InstallRoot `
    -InstallRustIfMissing
if ($LASTEXITCODE -ne 0) {
    throw "Unified runtime bootstrap failed with exit code $LASTEXITCODE"
}

$SmokeArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $Smoke,
    "-InstallRoot", $InstallRoot
)
if ($SkipCompile) { $SmokeArgs += "-SkipCompile" }
if ($SkipTrainingStep) { $SmokeArgs += "-SkipTrainingStep" }
if ($SkipControlCenter) { $SmokeArgs += "-SkipControlCenter" }

& powershell.exe @SmokeArgs
if ($LASTEXITCODE -ne 0) {
    throw "Unified runtime GPU smoke failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "MORTAL_ROGS_UNIFIED_WINDOWS_READY root=$InstallRoot"
