param(
    [string]$CoreRoot = "",
    [switch]$InstallRustIfMissing,
    [switch]$SkipRustBuild
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
if (-not $CoreRoot) {
    $CoreRoot = Join-Path $ProjectRoot "_runtime\core"
}
$CoreRoot = [System.IO.Path]::GetFullPath($CoreRoot)
$Bootstrap = Join-Path $ProjectRoot "scripts\bootstrap_runtime.ps1"
$Stage1 = Join-Path $ProjectRoot "scripts\patch_mortal_unified_stage1.py"
$Stage2 = Join-Path $ProjectRoot "scripts\patch_mortal_unified_stage2.py"
$SharedPatch = Join-Path $ProjectRoot "scripts\patch_mortal_4p.py"
$CanonicalCommit = "0cff2b52982be5b1163aa9a62fb01f03ce91e0d2"

foreach ($cmd in @("git", "python")) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $cmd"
    }
}

if (-not (Test-Path $CoreRoot)) {
    Write-Host "[1/5] Cloning canonical Mortal core..." -ForegroundColor Cyan
    git clone https://github.com/Equim-chan/Mortal.git $CoreRoot
    if ($LASTEXITCODE -ne 0) { throw "canonical Mortal clone failed" }
} else {
    Write-Host "[1/5] Unified core already exists: $CoreRoot"
}

if (-not (Test-Path (Join-Path $CoreRoot ".git"))) {
    throw "Unified core is not a Git checkout: $CoreRoot"
}

Write-Host "[2/5] Pinning canonical Mortal commit $CanonicalCommit..." -ForegroundColor Cyan
git -C $CoreRoot fetch origin $CanonicalCommit
if ($LASTEXITCODE -ne 0) { throw "failed to fetch canonical Mortal commit" }
git -C $CoreRoot checkout --detach $CanonicalCommit
if ($LASTEXITCODE -ne 0) { throw "failed to checkout canonical Mortal commit" }

# Reuse the proven Windows/PyTorch/Rust bootstrap, but do not apply the old
# 4P-only patch pipeline. This creates exactly one venv and one libriichi build.
Write-Host "[3/5] Preparing the single Python/Rust runtime..." -ForegroundColor Cyan
$args = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $Bootstrap,
    "-Mode", "4p",
    "-InstallRoot", $CoreRoot,
    "-SkipPatch"
)
if ($InstallRustIfMissing) { $args += "-InstallRustIfMissing" }
if ($SkipRustBuild) { $args += "-SkipRustBuild" }
& powershell.exe @args
if ($LASTEXITCODE -ne 0) {
    throw "single-core runtime bootstrap failed with exit code $LASTEXITCODE"
}

$Py = Join-Path $CoreRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Py -PathType Leaf)) {
    throw "Unified-core Python missing: $Py"
}

Write-Host "[4/5] Generalizing one Mortal model/trainer for 3P + 4P..." -ForegroundColor Cyan
& $Py $Stage1 --root $CoreRoot
if ($LASTEXITCODE -ne 0) { throw "unified model Stage 1 failed" }
& $Py $Stage2 --root $CoreRoot
if ($LASTEXITCODE -ne 0) { throw "unified trainer Stage 2 failed" }
& $Py $SharedPatch --root $CoreRoot
if ($LASTEXITCODE -ne 0) { throw "shared RTX/ROGS patch failed" }

Write-Host "[5/5] Verifying unified-core source layout..." -ForegroundColor Cyan
$Model = Join-Path $CoreRoot "mortal\model.py"
$Train = Join-Path $CoreRoot "mortal\train.py"
foreach ($path in @($Model, $Train)) {
    if (-not (Test-Path $path -PathType Leaf)) { throw "Missing unified-core file: $path" }
}
if (-not (Select-String -Path $Model -Pattern "MORTAL_ROGS_UNIFIED_MODEL_STAGE1" -Quiet)) {
    throw "Unified model marker missing"
}
if (-not (Select-String -Path $Train -Pattern "MORTAL_ROGS_UNIFIED_TRAINER_STAGE2" -Quiet)) {
    throw "Unified trainer marker missing"
}

Write-Host ""
Write-Host "MORTAL_UNIFIED_CORE_STAGE2_OK root=$CoreRoot" -ForegroundColor Green
Write-Host "One Mortal source tree: $CoreRoot"
Write-Host "One Python environment: $Py"
Write-Host "4P engine baseline: ready"
Write-Host "3P model/trainer dimensions: ready"
Write-Host "3P unified libriichi engine: pending next stage" -ForegroundColor Yellow
Write-Host "Do not replace the current user runtime with this core until 3P engine parity passes." -ForegroundColor Yellow
