param(
    [string]$InstallRoot = "",
    [switch]$InstallRustIfMissing,
    [switch]$InstallBuildToolsIfMissing,
    [switch]$SkipRustBuild,
    [switch]$SkipPatch
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
$MsvcHelper = Join-Path $PSScriptRoot "windows_msvc.ps1"
if (-not (Test-Path $MsvcHelper)) {
    throw "Missing MSVC helper: $MsvcHelper"
}
. $MsvcHelper

if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
    $InstallRoot = Join-Path (Split-Path $ProjectRoot -Parent) "Mortal_Unified"
}
$InstallRoot = [System.IO.Path]::GetFullPath($InstallRoot)
$CanonicalSha = "0cff2b52982be5b1163aa9a62fb01f03ce91e0d2"
$RepoUrl = "https://github.com/Equim-chan/Mortal.git"
$ManagedMarkerName = ".mortal-rogs-unified-runtime.json"
$ManagedMarker = Join-Path $InstallRoot $ManagedMarkerName
$ManagedResetRequired = $false
$ReuseManagedPatchedTree = $false

function Refresh-RustPath {
    $cargoBin = Join-Path $HOME ".cargo\bin"
    if (Test-Path $cargoBin) {
        $parts = @($env:PATH -split ';')
        if ($parts -notcontains $cargoBin) {
            $env:PATH = "$cargoBin;$env:PATH"
        }
    }
}

function Ensure-RustToolchain {
    if ($SkipRustBuild) { return }
    Refresh-RustPath
    if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
        if (-not $InstallRustIfMissing) {
            throw "Rust/Cargo is required. Rerun with -InstallRustIfMissing or install Rustlang.Rustup with WinGet."
        }
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
            throw "winget is unavailable; install Rust from rustup.rs and rerun."
        }
        Write-Host "[0/8] Installing Rustup..."
        & winget install --id Rustlang.Rustup --exact --source winget --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) {
            Refresh-RustPath
            if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
                throw "Rustup installation failed with exit code $LASTEXITCODE"
            }
        }
        Refresh-RustPath
    }
    if (-not (Get-Command rustup -ErrorAction SilentlyContinue)) {
        throw "rustup is unavailable after PATH refresh. Open a new PowerShell and rerun."
    }
    & rustup default stable-msvc
    if ($LASTEXITCODE -ne 0) { throw "rustup default stable-msvc failed" }
    Refresh-RustPath
    foreach ($cmd in @("cargo", "rustc")) {
        if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
            throw "$cmd is unavailable after rustup setup"
        }
    }
}

function Read-ManagedMarker {
    if (-not (Test-Path $ManagedMarker)) { return $null }
    try {
        $marker = Get-Content -LiteralPath $ManagedMarker -Raw | ConvertFrom-Json
    } catch {
        throw "Managed runtime marker is unreadable: $ManagedMarker"
    }
    if ([int]$marker.schema -ne 1) {
        throw "Unsupported managed runtime marker schema in $ManagedMarker"
    }
    if ([string]$marker.canonical_sha -ne $CanonicalSha) {
        throw "Managed runtime marker canonical SHA mismatch. Expected $CanonicalSha."
    }
    return $marker
}

function Write-ManagedMarker {
    $payload = [ordered]@{
        schema = 1
        canonical_sha = $CanonicalSha
        repo_url = $RepoUrl
        project_root = $ProjectRoot
        updated_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    } | ConvertTo-Json
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($ManagedMarker, $payload + [Environment]::NewLine, $utf8NoBom)
}

foreach ($cmd in @("git", "python")) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $cmd"
    }
}
Ensure-RustToolchain
if (-not $SkipRustBuild) {
    Ensure-MortalRogsMsvcBuildEnvironment -InstallIfMissing:$InstallBuildToolsIfMissing
}

if (-not (Test-Path $InstallRoot)) {
    Write-Host "[1/8] Cloning pinned canonical Mortal..."
    & git clone $RepoUrl $InstallRoot
    if ($LASTEXITCODE -ne 0) { throw "git clone failed" }
} else {
    if (-not (Test-Path (Join-Path $InstallRoot ".git"))) {
        throw "InstallRoot exists but is not a Git clone: $InstallRoot"
    }
    $dirty = @(& git -C $InstallRoot status --porcelain)
    if ($LASTEXITCODE -ne 0) { throw "git status failed for $InstallRoot" }
    if ($dirty.Count -gt 0) {
        $marker = Read-ManagedMarker
        if ($null -eq $marker) {
            throw "Unified runtime clone has local changes but no managed marker. Preserve them or use a fresh InstallRoot before bootstrap."
        }
        if ($SkipPatch) {
            $ReuseManagedPatchedTree = $true
            Write-Host "[1/8] Reusing managed patched Mortal tree (-SkipPatch): $InstallRoot"
        } else {
            $ManagedResetRequired = $true
            Write-Host "[1/8] Managed runtime detected; canonical source will be refreshed and patches reapplied."
        }
    } else {
        Write-Host "[1/8] Reusing clean Mortal clone: $InstallRoot"
    }
}

Write-Host "[2/8] Pinning canonical Mortal $CanonicalSha..."
& git -C $InstallRoot fetch origin
if ($LASTEXITCODE -ne 0) { throw "git fetch failed" }

if ($ReuseManagedPatchedTree) {
    $actualSha = (& git -C $InstallRoot rev-parse HEAD).Trim()
    if ($actualSha -ne $CanonicalSha) {
        throw "Managed patched runtime HEAD mismatch: expected $CanonicalSha, got $actualSha. Rerun without -SkipPatch to refresh it."
    }
} elseif ($ManagedResetRequired) {
    & git -C $InstallRoot reset --hard $CanonicalSha
    if ($LASTEXITCODE -ne 0) { throw "git reset --hard $CanonicalSha failed" }
    & git -C $InstallRoot clean -fd -e ".venv/" -e "runtime/" -e $ManagedMarkerName
    if ($LASTEXITCODE -ne 0) { throw "git clean of managed runtime failed" }
} else {
    & git -C $InstallRoot checkout --detach $CanonicalSha
    if ($LASTEXITCODE -ne 0) { throw "git checkout $CanonicalSha failed" }
}

$actualSha = (& git -C $InstallRoot rev-parse HEAD).Trim()
if ($actualSha -ne $CanonicalSha) { throw "Canonical SHA mismatch: $actualSha" }

$VenvRoot = Join-Path $InstallRoot ".venv"
$Py = Join-Path $VenvRoot "Scripts\python.exe"
if (-not (Test-Path $Py)) {
    Write-Host "[3/8] Creating one shared Python environment..."
    & python -m venv $VenvRoot
    if ($LASTEXITCODE -ne 0) { throw "python -m venv failed" }
} else {
    Write-Host "[3/8] Reusing shared venv: $VenvRoot"
}

Write-Host "[4/8] Installing RTX 5080 Python stack..."
& $Py -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
& $Py -m pip install torch==2.11.0 torchvision==0.26.0 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu128
if ($LASTEXITCODE -ne 0) { throw "PyTorch cu128 installation failed" }
& $Py -m pip install tqdm toml tensorboard maturin numpy pytest
if ($LASTEXITCODE -ne 0) { throw "Mortal dependency installation failed" }
& $Py -m pip install -r (Join-Path $ProjectRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Control Center dependency installation failed" }

if (-not $SkipPatch) {
    Write-Host "[5/8] Applying complete unified 3P/4P patch chain..."
    & $Py (Join-Path $ProjectRoot "scripts\patch_mortal_unified_all.py") --root $InstallRoot
    if ($LASTEXITCODE -ne 0) { throw "Unified patch chain failed" }
} else {
    Write-Host "[5/8] Skipping patch chain (-SkipPatch)."
}

if (-not $SkipRustBuild) {
    Write-Host "[6/8] Building the single unified libriichi extension..."
    Push-Location (Join-Path $InstallRoot "libriichi")
    try {
        & $Py -m maturin develop --release
        if ($LASTEXITCODE -ne 0) {
            throw "maturin develop failed after the MSVC link probe passed. Check the Rust/C++ compiler output above."
        }
    } finally {
        Pop-Location
    }
} else {
    Write-Host "[6/8] Skipping Rust build (-SkipRustBuild)."
}

Write-Host "[7/8] Generating isolated 3P and 4P configs inside one runtime..."
$env:ROGS_PROJECT_ROOT = $ProjectRoot
$env:ROGS_UNIFIED_ROOT = $InstallRoot
$ConfigScript = @'
from __future__ import annotations
import copy
import os
from pathlib import Path
import toml

project = Path(os.environ['ROGS_PROJECT_ROOT'])
root = Path(os.environ['ROGS_UNIFIED_ROOT'])
mortal = root / 'mortal'
example = mortal / 'config.example.toml'
if not example.is_file():
    raise FileNotFoundError(example)
base = toml.load(example)


def merge(dst, src):
    for key, value in src.items():
        if isinstance(value, dict) and isinstance(dst.get(key), dict):
            merge(dst[key], value)
        else:
            dst[key] = copy.deepcopy(value)


def ensure(d, key):
    value = d.get(key)
    if not isinstance(value, dict):
        value = {}
        d[key] = value
    return value

for mode, players, actions, obs_channels, oracle_channels, grp_size, overlay_name in (
    ('3p', 3, 44, 1010, 170, 6, 'rtx5080.sanma.toml'),
    ('4p', 4, 46, 1012, 217, 7, 'rtx5080.yonma.toml'),
):
    cfg = copy.deepcopy(base)
    overlay = project / 'config' / overlay_name
    if overlay.is_file():
        merge(cfg, toml.load(overlay))
    rogs = project / 'config' / 'rogs_runtime.toml'
    if rogs.is_file():
        merge(cfg, toml.load(rogs))

    game = ensure(cfg, 'game')
    game.update({
        'mode': mode,
        'num_players': players,
        'action_space': actions,
        'obs_channels': obs_channels,
        'oracle_obs_channels': oracle_channels,
        'grp_input_size': grp_size,
    })

    control = ensure(cfg, 'control')
    control['version'] = 4
    control['game_mode'] = mode
    control['online'] = False

    mode_root = root / 'runtime' / mode
    model_dir = mode_root / 'models'
    data_dir = mode_root / 'data'
    run_dir = mode_root / 'runs'
    online_dir = data_dir / 'online'
    for p in (model_dir, data_dir, run_dir, online_dir / 'buffer', online_dir / 'drain'):
        p.mkdir(parents=True, exist_ok=True)

    current = model_dir / 'current.pth'
    best = model_dir / 'best_mortal.pth'
    baseline = model_dir / 'baseline.pth'
    control['state_file'] = str(current)
    control['best_state_file'] = str(best)
    control['tensorboard_dir'] = str(run_dir / 'train')

    dataset = ensure(cfg, 'dataset')
    dataset['globs'] = [str(data_dir / '**' / '*.json.gz')]
    dataset['file_index'] = str(data_dir / 'file_index.pth')
    dataset['player_names_files'] = []

    baseline_cfg = ensure(cfg, 'baseline')
    ensure(baseline_cfg, 'train')['state_file'] = str(baseline)
    ensure(baseline_cfg, 'test')['state_file'] = str(baseline)

    online = ensure(cfg, 'online')
    server = ensure(online, 'server')
    server['buffer_dir'] = str(online_dir / 'buffer')
    server['drain_dir'] = str(online_dir / 'drain')

    train_play = ensure(cfg, 'train_play')
    ensure(train_play, 'default')['log_dir'] = str(run_dir / 'train_play')
    test_play = ensure(cfg, 'test_play')
    test_play['log_dir'] = str(run_dir / 'test_play')

    if mode == '3p':
        one = ensure(cfg, '1v2')
    else:
        one = ensure(cfg, '1v3')
    one['log_dir'] = str(run_dir / ('1v2' if mode == '3p' else '1v3'))
    ensure(one, 'challenger')['state_file'] = str(current)
    ensure(one, 'champion')['state_file'] = str(best)

    grp = ensure(cfg, 'grp')
    grp['state_file'] = str(model_dir / 'grp.pth')
    grp_control = ensure(grp, 'control')
    grp_control['tensorboard_dir'] = str(run_dir / 'grp')
    grp_dataset = ensure(grp, 'dataset')
    grp_dataset['train_globs'] = [str(data_dir / 'train' / '**' / '*.json.gz')]
    grp_dataset['val_globs'] = [str(data_dir / 'val' / '**' / '*.json.gz')]
    grp_dataset['file_index'] = str(data_dir / 'grp_file_index.pth')

    cfg_path = mortal / f'config.{mode}.toml'
    cfg_path.write_text(toml.dumps(cfg), encoding='utf-8')
    print(f'UNIFIED_CONFIG_OK {mode} {cfg_path}')
'@
& $Py -c $ConfigScript
if ($LASTEXITCODE -ne 0) { throw "Unified runtime config generation failed" }

Write-Host "[8/8] Verifying unified ABI and config files..."
$env:MORTAL_UNIFIED_ROOT = $InstallRoot
$env:PYTHONPATH = "$ProjectRoot;$InstallRoot\mortal"
$VerifyScript = @'
import os
from pathlib import Path
import toml
import libriichi
from libriichi import consts

root = Path(os.environ['MORTAL_UNIFIED_ROOT'])
assert consts.MAX_VERSION == 4
assert consts.num_players_for('3p') == 3
assert consts.num_players_for('4p') == 4
assert consts.action_space_for('3p') == 44
assert consts.action_space_for('4p') == 46
assert consts.obs_shape_for('3p', 4) == (1010, 34)
assert consts.obs_shape_for('4p', 4) == (1012, 34)
assert consts.oracle_obs_shape_for('3p', 4) == (170, 34)
assert consts.oracle_obs_shape_for('4p', 4) == (217, 34)
for mode, actions in [('3p', 44), ('4p', 46)]:
    cfg = toml.load(root / 'mortal' / f'config.{mode}.toml')
    assert cfg['control']['version'] == 4
    assert cfg['game']['mode'] == mode
    assert cfg['game']['action_space'] == actions
print('MORTAL_UNIFIED_RUNTIME_OK')
'@
& $Py -c $VerifyScript
if ($LASTEXITCODE -ne 0) { throw "Unified runtime ABI verification failed" }

Write-ManagedMarker

Write-Host ""
Write-Host "MORTAL_UNIFIED_BOOTSTRAP_OK root=$InstallRoot python=$Py"
Write-Host "Managed marker: $ManagedMarker"
Write-Host "3P config: $InstallRoot\mortal\config.3p.toml"
Write-Host "4P config: $InstallRoot\mortal\config.4p.toml"
Write-Host "One Python env: $VenvRoot"
Write-Host "One libriichi extension: $InstallRoot\libriichi"
