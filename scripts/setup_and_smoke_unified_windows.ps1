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
$CanonicalSha = "0cff2b52982be5b1163aa9a62fb01f03ce91e0d2"
$ManagedMarker = Join-Path $InstallRoot ".mortal-rogs-unified-runtime.json"

$Bootstrap = Join-Path $PSScriptRoot "bootstrap_unified_runtime.ps1"
$Smoke = Join-Path $PSScriptRoot "smoke_unified_windows.ps1"
foreach ($path in @($Bootstrap, $Smoke)) {
    if (-not (Test-Path $path)) {
        throw "Required unified runtime script is missing: $path"
    }
}

function Repair-PartialUnifiedBootstrap {
    if (-not (Test-Path $InstallRoot)) { return }
    if (-not (Test-Path (Join-Path $InstallRoot ".git"))) { return }
    if (Test-Path $ManagedMarker) { return }

    $dirty = @(& git -C $InstallRoot status --porcelain)
    if ($LASTEXITCODE -ne 0 -or $dirty.Count -eq 0) { return }

    $head = (& git -C $InstallRoot rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $head -ne $CanonicalSha) {
        throw "Partial unified runtime is dirty without a managed marker and is not at the pinned canonical SHA. Preserve it manually before rerunning: $InstallRoot"
    }

    $consts = Join-Path $InstallRoot "libriichi\src\consts.rs"
    $model = Join-Path $InstallRoot "mortal\model.py"
    $looksManaged = `
        (Test-Path $consts) -and `
        (Test-Path $model) -and `
        (Select-String -Path $consts -Pattern "MORTAL_ROGS_UNIFIED_ACTION_OBS_STAGE3E" -Quiet) -and `
        (Select-String -Path $model -Pattern "MORTAL_ROGS_UNIFIED_MODEL_STAGE1" -Quiet)

    if (-not $looksManaged) {
        throw "Unified runtime has unmarked local changes that are not recognized as a partial Mortal-ROGS bootstrap. Preserve them manually before rerunning: $InstallRoot"
    }

    Write-Host "Detected a partial managed bootstrap; restoring canonical source before retry..."
    & git -C $InstallRoot reset --hard $CanonicalSha
    if ($LASTEXITCODE -ne 0) { throw "Failed to reset partial unified runtime" }
    & git -C $InstallRoot clean -fd -e ".venv/" -e "runtime/"
    if ($LASTEXITCODE -ne 0) { throw "Failed to clean partial unified runtime" }
    Write-Host "MORTAL_UNIFIED_PARTIAL_RECOVERY_OK"
}

Write-Host "=== Mortal-ROGS unified Windows setup ==="
Write-Host "Runtime root: $InstallRoot"
Write-Host ""

Repair-PartialUnifiedBootstrap

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
