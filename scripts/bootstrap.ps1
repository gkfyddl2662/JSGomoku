param(
    [string]$RuntimeRoot = "$PSScriptRoot\..\..\Mortal_ROGS_Runtime",
    [switch]$SkipRustBuild,
    [switch]$InstallRustIfMissing,
    [switch]$SkipSmoke
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
$BootstrapAll = Join-Path $ProjectRoot "scripts\bootstrap_all_runtimes.ps1"

$args = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $BootstrapAll,
    "-RuntimeRoot", ([System.IO.Path]::GetFullPath($RuntimeRoot))
)
if ($SkipRustBuild) { $args += "-SkipRustBuild" }
if ($InstallRustIfMissing) { $args += "-InstallRustIfMissing" }
if ($SkipSmoke) { $args += "-SkipSmoke" }

Write-Host "Mortal-ROGS unified bootstrap" -ForegroundColor Cyan
Write-Host "Runtime root: $RuntimeRoot"
& powershell.exe @args
if ($LASTEXITCODE -ne 0) {
    throw "Unified Mortal-ROGS bootstrap failed with exit code $LASTEXITCODE"
}
