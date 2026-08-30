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
$LibriichiStage1 = Join-Path $ProjectRoot "scripts\patch_libriichi_unified_stage1.py"
$LibriichiStage2 = Join-Path $ProjectRoot "scripts\patch_libriichi_unified_stage2.py"
$ModelStage1 = Join-Path $ProjectRoot "scripts\patch_mortal_unified_stage1.py"
$TrainerStage2 = Join-Path $ProjectRoot "scripts\patch_mortal_unified_stage2.py"
$SharedPatch = Join-Path $ProjectRoot "scripts\patch_mortal_4p.py"
$CanonicalCommit = "0cff2b52982be5b1163aa9a62fb01f03ce91e0d2"

foreach ($cmd in @("git", "python")) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $cmd"
    }
}

if (-not (Test-Path $CoreRoot)) {
    Write-Host "[1/7] Cloning canonical Mortal core..." -ForegroundColor Cyan
    git clone https://github.com/Equim-chan/Mortal.git $CoreRoot
    if ($LASTEXITCODE -ne 0) { throw "canonical Mortal clone failed" }
} else {
    Write-Host "[1/7] Unified core already exists: $CoreRoot"
}

if (-not (Test-Path (Join-Path $CoreRoot ".git"))) {
    throw "Unified core is not a Git checkout: $CoreRoot"
}

Write-Host "[2/7] Pinning canonical Mortal commit $CanonicalCommit..." -ForegroundColor Cyan
git -C $CoreRoot fetch origin $CanonicalCommit
if ($LASTEXITCODE -ne 0) { throw "failed to fetch canonical Mortal commit" }
git -C $CoreRoot checkout --detach $CanonicalCommit
if ($LASTEXITCODE -ne 0) { throw "failed to checkout canonical Mortal commit" }

Write-Host "[3/7] Adding dual-mode contracts to the single libriichi crate..." -ForegroundColor Cyan
python $LibriichiStage1 --root $CoreRoot
if ($LASTEXITCODE -ne 0) { throw "unified libriichi Stage 1 failed" }
python $LibriichiStage2 --root $CoreRoot
if ($LASTEXITCODE -ne 0) { throw "unified libriichi Stage 2 failed" }

# Reuse the proven Windows/PyTorch/Rust bootstrap, but do not apply the old
# mode-specific patch pipeline. The single crate now accepts runtime-sized
# 44/46 action vectors before maturin builds it once.
Write-Host "[4/7] Building the single Python/Rust runtime..." -ForegroundColor Cyan
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

Write-Host "[5/7] Generalizing one Mortal model/trainer for 3P + 4P..." -ForegroundColor Cyan
& $Py $ModelStage1 --root $CoreRoot
if ($LASTEXITCODE -ne 0) { throw "unified model Stage 1 failed" }
& $Py $TrainerStage2 --root $CoreRoot
if ($LASTEXITCODE -ne 0) { throw "unified trainer Stage 2 failed" }
& $Py $SharedPatch --root $CoreRoot
if ($LASTEXITCODE -ne 0) { throw "shared RTX/ROGS patch failed" }

Write-Host "[6/7] Verifying unified-core source contracts..." -ForegroundColor Cyan
$Model = Join-Path $CoreRoot "mortal\model.py"
$Train = Join-Path $CoreRoot "mortal\train.py"
$Engine = Join-Path $CoreRoot "mortal\engine.py"
$Consts = Join-Path $CoreRoot "libriichi\src\consts.rs"
$Agent = Join-Path $CoreRoot "libriichi\src\agent\mortal.rs"
foreach ($path in @($Model, $Train, $Engine, $Consts, $Agent)) {
    if (-not (Test-Path $path -PathType Leaf)) { throw "Missing unified-core file: $path" }
}
if (-not (Select-String -Path $Model -Pattern "MORTAL_ROGS_UNIFIED_MODEL_STAGE1" -Quiet)) { throw "Unified model marker missing" }
if (-not (Select-String -Path $Train -Pattern "MORTAL_ROGS_UNIFIED_TRAINER_STAGE2" -Quiet)) { throw "Unified trainer marker missing" }
if (-not (Select-String -Path $Engine -Pattern "MORTAL_ROGS_UNIFIED_ENGINE_STAGE2" -Quiet)) { throw "Unified engine marker missing" }
if (-not (Select-String -Path $Consts -Pattern "MORTAL_ROGS_UNIFIED_LIBRIICHI_STAGE1" -Quiet)) { throw "Unified libriichi marker missing" }
if (-not (Select-String -Path $Agent -Pattern "MORTAL_ROGS_UNIFIED_AGENT_STAGE2" -Quiet)) { throw "Unified agent marker missing" }

Write-Host "[7/7] Probing the installed single libriichi module..." -ForegroundColor Cyan
if (-not $SkipRustBuild) {
    $Probe = @'
from libriichi.consts import (
    ACTION_SPACE_3P,
    ACTION_SPACE_4P,
    action_space_for,
    num_players_for,
    obs_shape_for,
)
assert ACTION_SPACE_3P == 44
assert ACTION_SPACE_4P == 46
assert action_space_for('3p') == 44
assert action_space_for('4p') == 46
assert num_players_for('3p') == 3
assert num_players_for('4p') == 4
assert obs_shape_for('3p', 4) == (1010, 34)
assert obs_shape_for('4p', 4) == (1012, 34)
print('MORTAL_UNIFIED_LIBRIICHI_CONTRACT_OK')
'@
    & $Py -c $Probe
    if ($LASTEXITCODE -ne 0) { throw "unified libriichi Python contract probe failed" }
}

Write-Host ""
Write-Host "MORTAL_UNIFIED_CORE_STAGE2_OK root=$CoreRoot" -ForegroundColor Green
Write-Host "One Mortal source tree: $CoreRoot"
Write-Host "One Python environment: $Py"
Write-Host "One libriichi module: dual-mode shape/action contract ready"
Write-Host "One Rust Mortal agent: runtime-sized 44/46 action vectors ready"
Write-Host "4P game engine: ready"
Write-Host "3P model/trainer dimensions: ready"
Write-Host "3P event translation + game state rules: pending Stage 3+" -ForegroundColor Yellow
Write-Host "Do not replace the current user runtime until 3P game parity passes." -ForegroundColor Yellow
