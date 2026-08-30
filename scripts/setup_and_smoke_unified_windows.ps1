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
$CanonicalRepo = "https://github.com/Equim-chan/Mortal.git"
$ManagedMarker = Join-Path $InstallRoot ".mortal-rogs-unified-runtime.json"

$Bootstrap = Join-Path $PSScriptRoot "bootstrap_unified_runtime.ps1"
$Smoke = Join-Path $PSScriptRoot "smoke_unified_windows.ps1"
foreach ($path in @($Bootstrap, $Smoke)) {
    if (-not (Test-Path $path)) {
        throw "Required unified runtime script is missing: $path"
    }
}

function Get-GitText {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$GitArgs
    )

    $output = & git @GitArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "git command failed: git $($GitArgs -join ' ')`n$($output | Out-String)"
    }
    return (($output | Out-String).Trim())
}

function Repair-PartialUnifiedBootstrap {
    if (-not (Test-Path $InstallRoot)) { return }
    if (-not (Test-Path (Join-Path $InstallRoot ".git"))) { return }
    if (Test-Path $ManagedMarker) { return }

    $dirtyText = Get-GitText -GitArgs @("-C", $InstallRoot, "status", "--porcelain=v1", "--untracked-files=all")
    if ([string]::IsNullOrWhiteSpace($dirtyText)) { return }

    $head = Get-GitText -GitArgs @("-C", $InstallRoot, "rev-parse", "HEAD")
    if ($head -ne $CanonicalSha) {
        throw "Unmarked dirty runtime is not at the pinned canonical SHA. Preserve it manually before rerunning: $InstallRoot"
    }

    $origin = Get-GitText -GitArgs @("-C", $InstallRoot, "config", "--get", "remote.origin.url")
    $originNormalized = $origin.TrimEnd('/')
    $canonicalNormalized = $CanonicalRepo.TrimEnd('/')
    if ($originNormalized -ne $canonicalNormalized) {
        throw "Unmarked dirty runtime does not point to the canonical Mortal repository. Preserve it manually: $InstallRoot"
    }

    $consts = Join-Path $InstallRoot "libriichi\src\consts.rs"
    $model = Join-Path $InstallRoot "mortal\model.py"
    $venvPython = Join-Path $InstallRoot ".venv\Scripts\python.exe"
    $pyproject = Join-Path $InstallRoot "libriichi\pyproject.toml"

    $hasRustMarker = (Test-Path $consts) -and (Select-String -Path $consts -Pattern "MORTAL_ROGS_UNIFIED_ACTION_OBS_STAGE3E" -Quiet)
    $hasModelMarker = (Test-Path $model) -and (Select-String -Path $model -Pattern "MORTAL_ROGS_UNIFIED_MODEL_STAGE1" -Quiet)
    $hasPackagingMarker = (Test-Path $pyproject) -and (Select-String -Path $pyproject -Pattern 'module-name\s*=\s*"libriichi"' -Quiet)
    $looksManaged = (Test-Path $venvPython) -and ($hasRustMarker -or $hasModelMarker -or $hasPackagingMarker)

    if (-not $looksManaged) {
        Write-Host "Unmarked dirty files detected:" -ForegroundColor Yellow
        Write-Host $dirtyText
        throw "Local changes are not recognized as a partial Mortal-ROGS bootstrap. Preserve them manually before rerunning: $InstallRoot"
    }

    Write-Host "Detected failed/partial Mortal-ROGS bootstrap. Restoring canonical source while preserving .venv and runtime data..."
    & git -C $InstallRoot reset --hard $CanonicalSha
    if ($LASTEXITCODE -ne 0) { throw "Failed to reset partial unified runtime" }
    & git -C $InstallRoot clean -fd -e ".venv/" -e "runtime/"
    if ($LASTEXITCODE -ne 0) { throw "Failed to clean partial unified runtime" }

    $remaining = Get-GitText -GitArgs @("-C", $InstallRoot, "status", "--porcelain=v1", "--untracked-files=all")
    if (-not [string]::IsNullOrWhiteSpace($remaining)) {
        throw "Partial recovery left unexpected source changes:`n$remaining"
    }
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
