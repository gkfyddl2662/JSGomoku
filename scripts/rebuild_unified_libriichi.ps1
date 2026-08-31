param(
    [string]$InstallRoot = ""
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
$Py = Join-Path $InstallRoot ".venv\Scripts\python.exe"
$LibriichiRoot = Join-Path $InstallRoot "libriichi"
$ArenaMod = Join-Path $LibriichiRoot "src\arena\mod.rs"
$OneVsTwo = Join-Path $LibriichiRoot "src\arena\one_vs_two.rs"

if (-not (Test-Path $Py)) {
    throw "Unified runtime Python not found: $Py"
}
if (-not (Test-Path $LibriichiRoot)) {
    throw "Unified libriichi source not found: $LibriichiRoot"
}

function Test-OneVsTwoSourceContract {
    if (-not (Test-Path $ArenaMod) -or -not (Test-Path $OneVsTwo)) {
        return $false
    }
    $modText = Get-Content -LiteralPath $ArenaMod -Raw
    $arenaText = Get-Content -LiteralPath $OneVsTwo -Raw
    return $modText.Contains("mod one_vs_two;") `
        -and $modText.Contains("m.add_class::<OneVsTwo>()?;") `
        -and $arenaText.Contains("MORTAL_ROGS_UNIFIED_GAME_STAGE5B")
}

if (-not (Test-OneVsTwoSourceContract)) {
    Write-Host "MORTAL_UNIFIED_3P_ARENA_SOURCE_STALE action=patch"
    & $Py (Join-Path $ProjectRoot "scripts\patch_mortal_unified_all.py") --root $InstallRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Unified patch chain failed while restoring OneVsTwo source"
    }
}
if (-not (Test-OneVsTwoSourceContract)) {
    throw "Unified libriichi source still does not expose OneVsTwo after patching"
}

$cargoBin = Join-Path $HOME ".cargo\bin"
if (Test-Path $cargoBin) {
    $parts = @($env:PATH -split ';')
    if ($parts -notcontains $cargoBin) {
        $env:PATH = "$cargoBin;$env:PATH"
    }
}

Ensure-MortalRogsMsvcBuildEnvironment

& $Py -m maturin --version *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "MORTAL_UNIFIED_3P_ARENA_BUILD_DEP action=install-maturin"
    & $Py -m pip install maturin
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install maturin into unified runtime"
    }
}

Write-Host "MORTAL_UNIFIED_3P_ARENA_REBUILD action=maturin-develop-release"
Push-Location $LibriichiRoot
try {
    & $Py -m maturin develop --release
    if ($LASTEXITCODE -ne 0) {
        throw "maturin develop --release failed for unified libriichi"
    }
} finally {
    Pop-Location
}

& $Py -c "import libriichi; assert hasattr(libriichi, 'arena'); assert hasattr(libriichi.arena, 'OneVsTwo'); print('MORTAL_UNIFIED_3P_ARENA_READY source=rebuilt-unified-libriichi')"
if ($LASTEXITCODE -ne 0) {
    throw "Rebuilt unified libriichi still does not expose arena.OneVsTwo"
}
