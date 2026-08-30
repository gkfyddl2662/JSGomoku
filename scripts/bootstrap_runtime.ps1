param(
    [ValidateSet("3p", "4p")]
    [string]$Mode = "3p",
    [Parameter(Mandatory=$true)]
    [string]$InstallRoot,
    [switch]$SkipRustBuild
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
$InstallRoot = [System.IO.Path]::GetFullPath($InstallRoot)

foreach ($cmd in @("git", "python")) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $cmd"
    }
}
if (-not $SkipRustBuild -and -not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    throw "cargo is required unless -SkipRustBuild is used"
}

$RepoUrl = if ($Mode -eq "3p") {
    "https://github.com/Lawrencelea/Mortal_Sanma.git"
} else {
    "https://github.com/Equim-chan/Mortal.git"
}

if (-not (Test-Path $InstallRoot)) {
    Write-Host "[1/7] Cloning $Mode Mortal runtime..."
    git clone $RepoUrl $InstallRoot
    if ($LASTEXITCODE -ne 0) { throw "git clone failed" }
} else {
    Write-Host "[1/7] Runtime already exists: $InstallRoot"
}

$VenvRoot = if ($Mode -eq "3p") { "$ProjectRoot\.venv" } else { "$InstallRoot\.venv" }
$Py = "$VenvRoot\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    Write-Host "[2/7] Creating isolated Python environment: $VenvRoot"
    python -m venv $VenvRoot
}

Write-Host "[3/7] Installing Python dependencies + Blackwell PyTorch cu128..."
& $Py -m pip install --upgrade pip
& $Py -m pip install torch==2.11.0 torchvision==0.26.0 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu128
& $Py -m pip install tqdm toml tensorboard maturin numpy pytest
if ($Mode -eq "3p") {
    & $Py -m pip install -r "$ProjectRoot\requirements.txt"
}

if (-not $SkipRustBuild) {
    $Libriichi = if ($Mode -eq "3p") { "$InstallRoot\Mortal\libriichi" } else { "$InstallRoot\libriichi" }
    Write-Host "[4/7] Building isolated libriichi extension: $Libriichi"
    Push-Location $Libriichi
    try {
        & $Py -m maturin develop --release
        if ($LASTEXITCODE -ne 0) { throw "maturin develop failed" }
    } finally {
        Pop-Location
    }

    if ($Mode -eq "3p" -and (Test-Path "$InstallRoot\tenhou_dl")) {
        Write-Host "[5/7] Building 3P Tenhou tools..."
        Push-Location "$InstallRoot\tenhou_dl"
        try {
            cargo build --release
            if ($LASTEXITCODE -ne 0) { throw "tenhou_dl build failed" }
        } finally {
            Pop-Location
        }
    } else {
        Write-Host "[5/7] No extra Rust data tool required for $Mode."
    }
} else {
    Write-Host "[4/7] Skipping libriichi build (-SkipRustBuild)."
    Write-Host "[5/7] Skipping optional Rust tools (-SkipRustBuild)."
}

Write-Host "[6/7] Applying RTX 5080 + ROGS patches..."
if ($Mode -eq "3p") {
    & $Py "$ProjectRoot\scripts\patch_mortal_all.py" --root $InstallRoot
} else {
    & $Py "$ProjectRoot\scripts\patch_mortal_4p.py" --root $InstallRoot
}
if ($LASTEXITCODE -ne 0) { throw "Mortal patch pipeline failed" }

Write-Host "[7/7] Creating runtime directories and config overlays..."
$env:ROGS_PROJECT_ROOT = $ProjectRoot
$env:ROGS_INSTALL_ROOT = $InstallRoot
$env:ROGS_MODE = $Mode
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$ProjectRoot;$env:PYTHONPATH" } else { $ProjectRoot }

$ConfigScript = @'
import os
from pathlib import Path
import toml

project = Path(os.environ['ROGS_PROJECT_ROOT'])
root = Path(os.environ['ROGS_INSTALL_ROOT'])
mode = os.environ['ROGS_MODE']

for rel in ('models', 'data', 'runs'):
    (root / rel).mkdir(parents=True, exist_ok=True)

if mode == '3p':
    mortal = root / 'Mortal' / 'mortal'
    cfg_path = mortal / 'config.sanma.toml'
    if not cfg_path.exists():
        raise FileNotFoundError(f'3P upstream config missing: {cfg_path}')
    cfg = toml.load(cfg_path)
    overlays = [project / 'config' / 'rtx5080.sanma.toml', project / 'config' / 'rogs_runtime.toml']
else:
    mortal = root / 'mortal'
    cfg_path = mortal / 'config.toml'
    example = mortal / 'config.example.toml'
    if cfg_path.exists():
        cfg = toml.load(cfg_path)
    else:
        cfg = toml.load(example)

    model_dir = root / 'models' / 'rogs_4p'
    data_dir = root / 'data'
    run_dir = root / 'runs' / '4p'
    online_dir = data_dir / 'online'
    for p in (model_dir, run_dir, online_dir / 'buffer', online_dir / 'drain'):
        p.mkdir(parents=True, exist_ok=True)

    current = model_dir / 'current.pth'
    best = model_dir / 'best_mortal.pth'
    baseline = model_dir / 'baseline.pth'

    cfg['control']['version'] = 4
    cfg['control']['state_file'] = str(current)
    cfg['control']['best_state_file'] = str(best)
    cfg['control']['tensorboard_dir'] = str(run_dir / 'train')
    cfg['train_play']['default']['log_dir'] = str(run_dir / 'train_play')
    cfg['test_play']['log_dir'] = str(run_dir / 'test_play')

    cfg['dataset']['globs'] = [str(data_dir / '**' / '*.json.gz')]
    cfg['dataset']['file_index'] = str(data_dir / 'file_index.pth')
    cfg['dataset']['player_names_files'] = []

    cfg['baseline']['train']['state_file'] = str(baseline)
    cfg['baseline']['test']['state_file'] = str(baseline)
    cfg['online']['server']['buffer_dir'] = str(online_dir / 'buffer')
    cfg['online']['server']['drain_dir'] = str(online_dir / 'drain')

    cfg['1v3']['log_dir'] = str(run_dir / '1v3')
    cfg['1v3']['challenger']['state_file'] = str(current)
    cfg['1v3']['champion']['state_file'] = str(best)

    cfg['grp']['state_file'] = str(model_dir / 'grp.pth')
    cfg['grp']['control']['tensorboard_dir'] = str(run_dir / 'grp')
    cfg['grp']['dataset']['train_globs'] = [str(data_dir / 'train' / '**' / '*.json.gz')]
    cfg['grp']['dataset']['val_globs'] = [str(data_dir / 'val' / '**' / '*.json.gz')]
    cfg['grp']['dataset']['file_index'] = str(data_dir / 'grp_file_index.pth')

    overlays = [project / 'config' / 'rtx5080.yonma.toml', project / 'config' / 'rogs_runtime.toml']

def merge(dst, src):
    for key, value in src.items():
        if isinstance(value, dict) and isinstance(dst.get(key), dict):
            merge(dst[key], value)
        else:
            dst[key] = value

for overlay in overlays:
    merge(cfg, toml.load(overlay))

cfg_path.write_text(toml.dumps(cfg), encoding='utf-8')
print(f'RUNTIME_CONFIG_OK {mode} {cfg_path}')
'@

& $Py -c $ConfigScript
if ($LASTEXITCODE -ne 0) { throw "Runtime config generation failed" }

Write-Host ""
Write-Host "MORTAL_RUNTIME_OK mode=$Mode root=$InstallRoot python=$Py"
if ($Mode -eq "3p") {
    Write-Host "Set: `$env:MORTAL_3P_ROOT='$InstallRoot'"
} else {
    Write-Host "Set: `$env:MORTAL_4P_ROOT='$InstallRoot'"
}
