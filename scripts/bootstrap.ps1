param(
    [string]$InstallRoot = "$PSScriptRoot\..\..\Mortal_Sanma",
    [switch]$SkipRustBuild
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $ProjectRoot
$InstallRoot = [System.IO.Path]::GetFullPath($InstallRoot)

Write-Host "[1/8] Checking tools..."
foreach ($cmd in @("git", "python")) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $cmd"
    }
}
if (-not $SkipRustBuild -and -not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    throw "cargo is required unless -SkipRustBuild is used"
}

if (-not (Test-Path $InstallRoot)) {
    Write-Host "[2/8] Cloning Mortal_Sanma..."
    git clone https://github.com/Lawrencelea/Mortal_Sanma.git $InstallRoot
} else {
    Write-Host "[2/8] Mortal_Sanma already exists: $InstallRoot"
}

Write-Host "[3/8] Creating WebUI virtual environment..."
if (-not (Test-Path "$ProjectRoot\.venv\Scripts\python.exe")) {
    python -m venv "$ProjectRoot\.venv"
}
$Py = "$ProjectRoot\.venv\Scripts\python.exe"
& $Py -m pip install --upgrade pip
& $Py -m pip install -r "$ProjectRoot\requirements.txt"

Write-Host "[4/8] Installing Blackwell-compatible PyTorch CUDA 12.8..."
& $Py -m pip install torch==2.11.0 torchvision==0.26.0 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu128
& $Py -m pip install tqdm toml tensorboard maturin numpy pytest

if (-not $SkipRustBuild) {
    Write-Host "[5/8] Building libriichi with maturin..."
    Push-Location "$InstallRoot\Mortal\libriichi"
    try {
        & $Py -m maturin develop --release
    } finally {
        Pop-Location
    }

    Write-Host "[6/8] Building Tenhou tools..."
    Push-Location "$InstallRoot\tenhou_dl"
    try {
        cargo build --release
    } finally {
        Pop-Location
    }
} else {
    Write-Host "[5/8] Skipping libriichi build (-SkipRustBuild)."
    Write-Host "[6/8] Skipping Tenhou tools build (-SkipRustBuild)."
}

Write-Host "[7/8] Applying RTX 5080 + ROGS trainer patches..."
& $Py "$ProjectRoot\scripts\patch_mortal_all.py" --root $InstallRoot
if ($LASTEXITCODE -ne 0) {
    throw "Mortal patch pipeline failed with exit code $LASTEXITCODE"
}

Write-Host "[8/8] Merging RTX 5080 and ROGS runtime overlays..."
$env:MORTAL_SANMA_ROOT = $InstallRoot
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$ProjectRoot;$env:PYTHONPATH" } else { $ProjectRoot }
& $Py -c "import toml, pathlib; p=pathlib.Path(r'$InstallRoot')/'Mortal'/'mortal'/'config.sanma.toml'; base=toml.load(p); overlays=[pathlib.Path(r'$ProjectRoot')/'config'/'rtx5080.sanma.toml', pathlib.Path(r'$ProjectRoot')/'config'/'rogs_runtime.toml']; exec('def m(a,b):\n for k,v in b.items():\n  m(a[k],v) if isinstance(v,dict) and isinstance(a.get(k),dict) else a.__setitem__(k,v)'); [m(base,toml.load(x)) for x in overlays]; p.write_text(toml.dumps(base), encoding='utf-8')"
if ($LASTEXITCODE -ne 0) {
    throw "Config overlay merge failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "Done. RTX 5080 runtime + ROGS hook are installed."
Write-Host "Start with:"
Write-Host "  `$env:MORTAL_SANMA_ROOT='$InstallRoot'"
Write-Host "  `$env:PYTHONPATH='$ProjectRoot'"
Write-Host "  & '$Py' -m app.main"
Write-Host "Open http://127.0.0.1:8188"
