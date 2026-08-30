param(
    [string]$InstallRoot = "",
    [switch]$SkipCompile,
    [switch]$SkipTrainingStep,
    [switch]$SkipGameplay,
    [switch]$SkipRealDataTraining,
    [switch]$SkipEvaluator,
    [switch]$SkipControlCenter
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
    $InstallRoot = Join-Path (Split-Path $ProjectRoot -Parent) "Mortal_Unified"
}
$InstallRoot = [System.IO.Path]::GetFullPath($InstallRoot)
$Py = Join-Path $InstallRoot ".venv\Scripts\python.exe"
$MortalDir = Join-Path $InstallRoot "mortal"
$Config3P = Join-Path $MortalDir "config.3p.toml"
$Config4P = Join-Path $MortalDir "config.4p.toml"

foreach ($path in @($Py, $Config3P, $Config4P)) {
    if (-not (Test-Path $path)) {
        throw "Unified runtime is incomplete; missing: $path"
    }
}

function Invoke-NativeCapture {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $previousErrorAction = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & $Executable @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorAction
    }

    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = (($output | Out-String).Trim())
    }
}

function Get-TritonVersion {
    $probe = Invoke-NativeCapture -Executable $Py -Arguments @(
        "-c",
        "import triton; print(triton.__version__)"
    )
    if ($probe.ExitCode -ne 0) { return $null }
    $version = $probe.Output.Trim()
    if ([string]::IsNullOrWhiteSpace($version)) { return $null }
    return $version
}

function Get-InstalledGameplayAbi {
    $probe = Invoke-NativeCapture -Executable $Py -Arguments @(
        "-c",
        "import libriichi; print(getattr(libriichi.dataset, 'UNIFIED_GAMEPLAY_ABI', 0))"
    )
    if ($probe.ExitCode -ne 0) { return 0 }
    $value = 0
    if (-not [int]::TryParse($probe.Output.Trim(), [ref]$value)) { return 0 }
    return $value
}

$env:MORTAL_UNIFIED_ROOT = $InstallRoot
$existingPythonPath = $env:PYTHONPATH
$parts = @($ProjectRoot, $MortalDir)
if (-not [string]::IsNullOrWhiteSpace($existingPythonPath)) {
    $parts += $existingPythonPath
}
$env:PYTHONPATH = [string]::Join([System.IO.Path]::PathSeparator, $parts)

if (-not $SkipCompile) {
    Write-Host "[0/5] Verifying Windows Triton for torch.compile..."
    $tritonVersion = Get-TritonVersion
    if ([string]::IsNullOrWhiteSpace($tritonVersion) -or -not $tritonVersion.StartsWith("3.6")) {
        Write-Host "Installing compatible triton-windows 3.6.x for PyTorch 2.11..."
        $install = Invoke-NativeCapture -Executable $Py -Arguments @(
            "-m", "pip", "install", "-U", "triton-windows>=3.6,<3.7"
        )
        if ($install.ExitCode -ne 0) {
            throw "Failed to install triton-windows 3.6.x into unified runtime venv:`n$($install.Output)"
        }
        if (-not [string]::IsNullOrWhiteSpace($install.Output)) { Write-Host $install.Output }
        $tritonVersion = Get-TritonVersion
        if ([string]::IsNullOrWhiteSpace($tritonVersion) -or -not $tritonVersion.StartsWith("3.6")) {
            $details = Invoke-NativeCapture -Executable $Py -Arguments @(
                "-c",
                "import sys; print(sys.executable); import triton; print(triton.__version__)"
            )
            throw "Triton import/version check failed after installation. Probe output:`n$($details.Output)"
        }
    }
    Write-Host "TRITON_WINDOWS_OK version=$tritonVersion"
}

$gameplayAbi = Get-InstalledGameplayAbi
if ($gameplayAbi -lt 2) {
    Write-Host "[0.25/5] Upgrading unified native gameplay dataset ABI to v2..."
    & $Py (Join-Path $ProjectRoot "scripts\patch_libriichi_unified_dataset_stage8b.py") --root $InstallRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to apply unified gameplay dataset Stage 8B"
    }

    $cargoBin = Join-Path $HOME ".cargo\bin"
    if (Test-Path $cargoBin) {
        $pathParts = @($env:PATH -split ';')
        if ($pathParts -notcontains $cargoBin) {
            $env:PATH = "$cargoBin;$env:PATH"
        }
    }
    $MsvcHelper = Join-Path $ProjectRoot "scripts\windows_msvc.ps1"
    if (-not (Test-Path $MsvcHelper)) { throw "Missing MSVC helper: $MsvcHelper" }
    . $MsvcHelper
    Ensure-MortalRogsMsvcBuildEnvironment

    Push-Location (Join-Path $InstallRoot "libriichi")
    try {
        & $Py -m maturin develop --release
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to rebuild libriichi after Stage 8B gameplay ABI patch"
        }
    } finally {
        Pop-Location
    }

    $gameplayAbi = Get-InstalledGameplayAbi
    if ($gameplayAbi -lt 2) {
        throw "Rebuilt libriichi does not expose UNIFIED_GAMEPLAY_ABI=2 (got $gameplayAbi)"
    }
    Write-Host "MORTAL_UNIFIED_DATASET_STAGE8B_REBUILT abi=$gameplayAbi"
} else {
    Write-Host "MORTAL_UNIFIED_DATASET_STAGE8B_OK abi=$gameplayAbi"
}

Write-Host "[0.5/5] Repairing/verifying unified Python ABI imports and evaluators..."
foreach ($patch in @(
    "patch_mortal_unified_stage1.py",
    "patch_mortal_unified_eval_stage8c.py",
    "patch_mortal_unified_python_abi_stage8a.py"
)) {
    $patchPath = Join-Path $ProjectRoot "scripts\$patch"
    & $Py $patchPath --root $InstallRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to apply unified Python ABI/evaluator compatibility patch: $patch"
    }
}
$modelImportProbe = Invoke-NativeCapture -Executable $Py -Arguments @(
    "-c",
    "import os, sys; from pathlib import Path; os.environ['MORTAL_CFG']=r'$Config4P'; root=Path(r'$MortalDir'); sys.path.insert(0, str(root)); import libriichi; from libriichi import consts, arena, dataset, stat; import model, engine, player, dataloader, train_grp; eval4=(root/'one_vs_three.py').read_text(encoding='utf-8'); assert getattr(dataset, 'UNIFIED_GAMEPLAY_ABI', 0) >= 2; assert getattr(player, 'MODE', None) == '4p'; assert getattr(player, 'ACTION_SPACE', None) == 46; assert 'MORTAL_ROGS_UNIFIED_EVAL_STAGE8C' in eval4; assert 'ACTION_SPACE = 46' in eval4; print('MORTAL_UNIFIED_MODEL_IMPORT_OK', libriichi.__file__, consts.MAX_VERSION); print('MORTAL_UNIFIED_PYTHON_ABI_STAGE8A_IMPORT_OK'); print('MORTAL_UNIFIED_DATASET_STAGE8B_IMPORT_OK', dataset.UNIFIED_GAMEPLAY_ABI); print('MORTAL_UNIFIED_EVAL_STAGE8C_IMPORT_OK')"
)
if ($modelImportProbe.ExitCode -ne 0) {
    throw "Unified Python ABI/evaluator import probe failed:`n$($modelImportProbe.Output)"
}
Write-Host $modelImportProbe.Output

Write-Host "[1/5] Running one-process 3P -> 4P CUDA/BF16 runtime smoke..."
$smokeArgs = @(
    (Join-Path $ProjectRoot "scripts\smoke_unified_runtime.py"),
    "--runtime-root",
    $InstallRoot
)
if ($SkipCompile) { $smokeArgs += "--skip-compile" }
if ($SkipTrainingStep) { $smokeArgs += "--skip-training-step" }
& $Py @smokeArgs
if ($LASTEXITCODE -ne 0) {
    throw "Unified CUDA runtime smoke failed with exit code $LASTEXITCODE"
}

if (-not $SkipGameplay) {
    Write-Host "[2/5] Running real 3P + 4P arena/log/dataset gameplay E2E..."
    & $Py (Join-Path $ProjectRoot "scripts\smoke_unified_gameplay.py") --runtime-root $InstallRoot --device cuda:0
    if ($LASTEXITCODE -ne 0) {
        throw "Unified gameplay E2E smoke failed with exit code $LASTEXITCODE"
    }
} else {
    Write-Host "[2/5] Skipping real gameplay E2E (-SkipGameplay)."
}

$trainedCheckpointRequired = $false
if (-not $SkipRealDataTraining) {
    Write-Host "[3/5] Training one mini-batch from real 3P/4P self-play logs and strict-reloading checkpoints..."
    & $Py (Join-Path $ProjectRoot "scripts\smoke_unified_training.py") --runtime-root $InstallRoot --device cuda:0 --batch-size 16
    if ($LASTEXITCODE -ne 0) {
        throw "Unified real-data mini-training E2E failed with exit code $LASTEXITCODE"
    }
    $trainedCheckpointRequired = $true
} else {
    Write-Host "[3/5] Skipping real-data mini-training (-SkipRealDataTraining)."
}

if (-not $SkipEvaluator) {
    Write-Host "[4/5] Running strict checkpoint reload + real 3P/4P evaluator E2E..."
    $evalArgs = @(
        (Join-Path $ProjectRoot "scripts\smoke_unified_evaluator.py"),
        "--runtime-root",
        $InstallRoot,
        "--device",
        "cuda:0"
    )
    if ($trainedCheckpointRequired) { $evalArgs += "--require-trained-checkpoints" }
    & $Py @evalArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Unified checkpoint/evaluator E2E smoke failed with exit code $LASTEXITCODE"
    }
} else {
    Write-Host "[4/5] Skipping checkpoint/evaluator E2E (-SkipEvaluator)."
}

if (-not $SkipControlCenter) {
    Write-Host "[5/5] Verifying Control Center uses the same root, Python and Mortal code for both modes..."
    $ControlCenterProbe = @'
from pathlib import Path
from app.settings import load_settings
from app.mortal import MortalController

settings = load_settings()
controller = MortalController(settings)
r3 = settings.runtime('3p')
r4 = settings.runtime('4p')
assert r3.unified and r4.unified
assert r3.root == r4.root
assert r3.python_executable == r4.python_executable
assert r3.mortal_dir == r4.mortal_dir
assert r3.config_file != r4.config_file
assert r3.mode_root != r4.mode_root
assert r3.models_dir != r4.models_dir
assert r3.data_dir != r4.data_dir
assert r3.runs_dir != r4.runs_dir

s3 = controller.status('3p')
s4 = controller.status('4p')
assert s3['ready'], s3
assert s4['ready'], s4
assert s3['python'] == s4['python']
assert s3['mortal_dir'] == s4['mortal_dir']

for mode, expected_eval in [('3p', 'one_vs_two.py'), ('4p', 'one_vs_three.py')]:
    cmd, cwd, env = controller.command_for('evaluate', {'mode': mode})
    assert Path(cmd[0]).resolve() == r3.python_executable.resolve()
    assert cmd[1] == expected_eval
    assert Path(cwd).resolve() == r3.mortal_dir.resolve()
    assert env['MORTAL_GAME_MODE'] == mode
    assert Path(env['MORTAL_UNIFIED_ROOT']).resolve() == r3.root.resolve()

print('CONTROL_CENTER_UNIFIED_RUNTIME_OK')
'@
    & $Py -c $ControlCenterProbe
    if ($LASTEXITCODE -ne 0) {
        throw "Control Center unified routing probe failed with exit code $LASTEXITCODE"
    }
} else {
    Write-Host "[5/5] Skipping Control Center probe (-SkipControlCenter)."
}

Write-Host ""
Write-Host "WINDOWS_UNIFIED_RUNTIME_SMOKE_OK root=$InstallRoot python=$Py"
