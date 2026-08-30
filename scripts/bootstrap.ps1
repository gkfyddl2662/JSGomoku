param(
    [string]$InstallRoot = "$PSScriptRoot\..\..\Mortal_Sanma",
    [switch]$SkipRustBuild
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $ProjectRoot
$InstallRoot = [System.IO.Path]::GetFullPath($InstallRoot)

Write-Host "[1/7] Checking tools..."
foreach ($cmd in @("git", "python", "cargo")) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $cmd"
    }
}

if (-not (Test-Path $InstallRoot)) {
    Write-Host "[2/7] Cloning Mortal_Sanma..."
    git clone https://github.com/Lawrencelea/Mortal_Sanma.git $InstallRoot
} else {
    Write-Host "[2/7] Mortal_Sanma already exists: $InstallRoot"
}

Write-Host "[3/7] Creating WebUI virtual environment..."
if (-not (Test-Path "$ProjectRoot\.venv\Scripts\python.exe")) {
    python -m venv "$ProjectRoot\.venv"
}
$Py = "$ProjectRoot\.venv\Scripts\python.exe"
& $Py -m pip install --upgrade pip
& $Py -m pip install -r "$ProjectRoot\requirements.txt"

Write-Host "[4/7] Installing Blackwell-compatible PyTorch CUDA 12.8..."
& $Py -m pip install torch==2.11.0 torchvision==0.26.0 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu128
& $Py -m pip install tqdm toml tensorboard maturin numpy

if (-not $SkipRustBuild) {
    Write-Host "[5/7] Building libriichi with maturin..."
    Push-Location "$InstallRoot\Mortal\libriichi"
    & $Py -m maturin develop --release
    Pop-Location

    Write-Host "[6/7] Building Tenhou tools..."
    Push-Location "$InstallRoot\tenhou_dl"
    cargo build --release
    Pop-Location
}

Write-Host "[7/7] Applying RTX 5080 patch + preset..."
& $Py "$ProjectRoot\scripts\patch_mortal.py" --root $InstallRoot
$env:MORTAL_SANMA_ROOT = $InstallRoot
& $Py -c "import toml, pathlib; p=pathlib.Path(r'$InstallRoot')/'Mortal'/'mortal'/'config.sanma.toml'; base=toml.load(p); pre=toml.load(pathlib.Path(r'$ProjectRoot')/'config'/'rtx5080.sanma.toml'); exec('def m(a,b):\n for k,v in b.items():\n  m(a[k],v) if isinstance(v,dict) and isinstance(a.get(k),dict) else a.__setitem__(k,v)'); m(base,pre); p.write_text(toml.dumps(base), encoding='utf-8')"

Write-Host ""
Write-Host "Done. Start with:"
Write-Host "  `$env:MORTAL_SANMA_ROOT='$InstallRoot'"
Write-Host "  & '$Py' -m app.main"
Write-Host "Open http://127.0.0.1:8188"
