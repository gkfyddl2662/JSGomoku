param(
    [ValidateSet("Validate", "Experiment", "Full")]
    [string]$RunMode = "Validate",
    [ValidateSet("both", "3p", "4p")]
    [string]$GameModes = "both",
    [string]$InstallRoot = "",
    [ValidateSet("error", "fresh", "resume")]
    [string]$ExistingPolicy = "error",
    [int]$TrainingSeed = 36887,
    [int]$SeedStart = 10000,
    [int]$SeedCount = 100,
    [string]$SeedKey = "0xD5DFAA4CEF265CD7",
    [string]$Device = "cuda:0",
    [string]$RatingProfile = "",
    [double]$SoakMinutes = 30.0,
    [int]$SoakConcurrency = 8,
    [int]$SoakBatchRows = 1,
    [int]$InferencePort = 8190,
    [string]$InferenceApiKey = "mortal-rogs-local",
    [switch]$SkipBootstrap,
    [switch]$SkipSmoke,
    [switch]$SkipSoak,
    [switch]$OpenResults
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
    $InstallRoot = Join-Path (Split-Path $ProjectRoot -Parent) "Mortal_Unified"
}
$InstallRoot = [System.IO.Path]::GetFullPath($InstallRoot)
$Py = Join-Path $InstallRoot ".venv\Scripts\python.exe"
$MortalDir = Join-Path $InstallRoot "mortal"
$Timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMdd-HHmmss")
$SuiteRoot = Join-Path $InstallRoot "runtime\local-suite\$Timestamp-$($RunMode.ToLowerInvariant())"
$Steps = [System.Collections.Generic.List[object]]::new()
$Comparisons = [System.Collections.Generic.List[object]]::new()
$InferenceProcess = $null

if ($TrainingSeed -lt 0) { throw "TrainingSeed must be non-negative" }
if ($SeedStart -lt 0) { throw "SeedStart must be non-negative" }
if ($SeedCount -le 0) { throw "SeedCount must be positive" }
if ($SoakMinutes -le 0) { throw "SoakMinutes must be positive" }
if ($SoakConcurrency -le 0 -or $SoakBatchRows -le 0) { throw "SoakConcurrency and SoakBatchRows must be positive" }
if ($InferencePort -lt 1 -or $InferencePort -gt 65535) { throw "InferencePort must be between 1 and 65535" }

$SelectedModes = if ($GameModes -eq "both") { @("3p", "4p") } else { @($GameModes) }

function Invoke-CheckedNative {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$CommandArgs,
        [string]$WorkingDirectory = ""
    )

    $pushed = $false
    try {
        if (-not [string]::IsNullOrWhiteSpace($WorkingDirectory)) {
            Push-Location $WorkingDirectory
            $pushed = $true
        }
        & $Executable @CommandArgs
        $exitCode = $LASTEXITCODE
    } finally {
        if ($pushed) { Pop-Location }
    }
    if ($exitCode -ne 0) {
        throw "Command failed with exit code $exitCode: $Executable $($CommandArgs -join ' ')"
    }
}

function Invoke-SuiteStep {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )

    Write-Host ""
    Write-Host "=== $Name ===" -ForegroundColor Cyan
    $started = Get-Date
    try {
        & $Action
        $elapsed = ((Get-Date) - $started).TotalSeconds
        $Steps.Add([pscustomobject]@{ name = $Name; ok = $true; elapsed_s = [math]::Round($elapsed, 3) })
        Write-Host "OK: $Name" -ForegroundColor Green
    } catch {
        $elapsed = ((Get-Date) - $started).TotalSeconds
        $Steps.Add([pscustomobject]@{ name = $Name; ok = $false; elapsed_s = [math]::Round($elapsed, 3); error = $_.Exception.Message })
        throw
    }
}

function Assert-ExperimentPrerequisites {
    foreach ($mode in $SelectedModes) {
        $modeRoot = Join-Path $InstallRoot "runtime\$mode"
        $dataDir = Join-Path $modeRoot "data"
        $modelDir = Join-Path $modeRoot "models"
        $configPath = Join-Path $MortalDir "config.$mode.toml"
        foreach ($required in @($Py, $configPath, (Join-Path $modelDir "baseline.pth"), (Join-Path $modelDir "grp.pth"))) {
            if (-not (Test-Path $required)) {
                throw "$mode experiment prerequisite is missing: $required"
            }
        }
        $dataCount = @(Get-ChildItem -LiteralPath $dataDir -Recurse -File -Filter "*.json.gz" -ErrorAction SilentlyContinue).Count
        if ($dataCount -lt 1) {
            throw "$mode has no real training *.json.gz files under $dataDir"
        }
        Write-Host "PREFLIGHT_OK mode=$mode data_files=$dataCount baseline=baseline.pth grp=grp.pth"
    }
}

function Get-AblationCheckpointRelative {
    param([string]$Mode, [string]$Variant)
    return "ablation\seed-$TrainingSeed\$Variant\current.pth"
}

function Invoke-Ablation {
    param([string]$Mode, [string]$Variant)

    $commandArgs = @(
        (Join-Path $ProjectRoot "scripts\run_training_ablation.py"),
        "--runtime-root", $InstallRoot,
        "--mode", $Mode,
        "--variant", $Variant,
        "--seed", [string]$TrainingSeed
    )
    if ($ExistingPolicy -eq "fresh") { $commandArgs += "--fresh" }
    elseif ($ExistingPolicy -eq "resume") { $commandArgs += "--resume" }
    Invoke-CheckedNative -Executable $Py -CommandArgs $commandArgs -WorkingDirectory $ProjectRoot
}

function Invoke-Comparison {
    param([string]$Mode, [string]$Variant)

    $candidate = Get-AblationCheckpointRelative -Mode $Mode -Variant $Variant
    $baseline = Get-AblationCheckpointRelative -Mode $Mode -Variant "mortal"
    $comparisonRoot = Join-Path $SuiteRoot "$Mode\$Variant-vs-mortal"
    $commandArgs = @(
        (Join-Path $ProjectRoot "scripts\run_model_comparison.py"),
        "--runtime-root", $InstallRoot,
        "--mode", $Mode,
        "--candidate", $candidate,
        "--baseline", $baseline,
        "--candidate-name", $Variant,
        "--baseline-name", "mortal",
        "--seed-start", [string]$SeedStart,
        "--seed-count", [string]$SeedCount,
        "--seed-key", $SeedKey,
        "--device", $Device,
        "--output-root", $comparisonRoot
    )
    if (-not [string]::IsNullOrWhiteSpace($RatingProfile)) {
        $commandArgs += @("--profile", $RatingProfile)
    }
    Invoke-CheckedNative -Executable $Py -CommandArgs $commandArgs -WorkingDirectory $ProjectRoot

    $manifest = Join-Path $comparisonRoot "comparison.json"
    if (-not (Test-Path $manifest)) { throw "Comparison manifest was not created: $manifest" }
    $result = Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json
    $Comparisons.Add($result)
}

function Get-ServingCheckpoint {
    param([string]$Mode)

    $models = Join-Path $InstallRoot "runtime\$Mode\models"
    $ablation = Join-Path $models (Get-AblationCheckpointRelative -Mode $Mode -Variant "rogs-global")
    if (Test-Path $ablation) { return $ablation }
    $best = Join-Path $models "best_mortal.pth"
    if (Test-Path $best) { return $best }
    throw "Serving soak needs a valid $Mode checkpoint. Expected $ablation or $best"
}

function Wait-InferenceReady {
    param([string]$Server, [string]$ApiKey)
    $deadline = (Get-Date).AddMinutes(3)
    $headers = @{}
    if (-not [string]::IsNullOrWhiteSpace($ApiKey)) { $headers["Authorization"] = $ApiKey }
    do {
        if ($null -ne $InferenceProcess -and $InferenceProcess.HasExited) {
            throw "Inference server exited early with code $($InferenceProcess.ExitCode)"
        }
        try {
            $response = Invoke-RestMethod -Uri "$Server/health" -Headers $headers -TimeoutSec 5
            if ($response.protocol -eq "akagiot-v1") { return }
        } catch {
            Start-Sleep -Seconds 2
        }
    } while ((Get-Date) -lt $deadline)
    throw "Inference API did not become ready within 3 minutes: $Server"
}

function Start-SoakServer {
    $model3 = Get-ServingCheckpoint -Mode "3p"
    $model4 = Get-ServingCheckpoint -Mode "4p"
    $stdout = Join-Path $SuiteRoot "inference.stdout.log"
    $stderr = Join-Path $SuiteRoot "inference.stderr.log"
    $arguments = @(
        (Join-Path $ProjectRoot "scripts\serve_akagi_api.py"),
        "--runtime-root", $InstallRoot,
        "--host", "127.0.0.1",
        "--port", [string]$InferencePort,
        "--device", $Device,
        "--api-key", $InferenceApiKey,
        "--model-3p", $model3,
        "--model-4p", $model4
    )
    $script:InferenceProcess = Start-Process -FilePath $Py -ArgumentList $arguments -WorkingDirectory $ProjectRoot -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    Wait-InferenceReady -Server "http://127.0.0.1:$InferencePort" -ApiKey $InferenceApiKey
    Write-Host "INFERENCE_READY pid=$($InferenceProcess.Id) model3=$model3 model4=$model4"
}

function Stop-SoakServer {
    if ($null -eq $InferenceProcess) { return }
    try {
        if (-not $InferenceProcess.HasExited) {
            Stop-Process -Id $InferenceProcess.Id -ErrorAction SilentlyContinue
            $InferenceProcess.WaitForExit(10000) | Out-Null
        }
    } finally {
        $script:InferenceProcess = $null
    }
}

function Invoke-ServingSoak {
    Start-SoakServer
    try {
        $duration = [math]::Round($SoakMinutes * 60.0, 3)
        $soakOutput = Join-Path $SuiteRoot "serving-soak.json"
        $commandArgs = @(
            (Join-Path $ProjectRoot "scripts\soak_inference_api.py"),
            "--server", "http://127.0.0.1:$InferencePort",
            "--api-key", $InferenceApiKey,
            "--modes", $GameModes,
            "--duration-s", [string]$duration,
            "--min-production-duration-s", [string]$duration,
            "--concurrency", [string]$SoakConcurrency,
            "--batch-rows", [string]$SoakBatchRows,
            "--require-gpu-telemetry",
            "--fail-on-gate",
            "--output", $soakOutput
        )
        Invoke-CheckedNative -Executable $Py -CommandArgs $commandArgs -WorkingDirectory $ProjectRoot
    } finally {
        Stop-SoakServer
    }
}

function Get-GpuSnapshot {
    $nvidia = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if ($null -eq $nvidia) { return $null }
    try {
        $row = (& $nvidia.Source --query-gpu=index,name,driver_version,memory.total --format=csv,noheader,nounits 2>$null | Select-Object -First 1)
        if ([string]::IsNullOrWhiteSpace($row)) { return $null }
        return $row.Trim()
    } catch {
        return $null
    }
}

New-Item -ItemType Directory -Force -Path $SuiteRoot | Out-Null
$Transcript = Join-Path $SuiteRoot "local-suite.log"
Start-Transcript -Path $Transcript -Force | Out-Null

try {
    Write-Host "Mortal-ROGS local workstation suite" -ForegroundColor Yellow
    Write-Host "RunMode=$RunMode GameModes=$GameModes ExistingPolicy=$ExistingPolicy"
    Write-Host "ProjectRoot=$ProjectRoot"
    Write-Host "InstallRoot=$InstallRoot"
    Write-Host "Results=$SuiteRoot"

    if (-not $SkipBootstrap -and -not $SkipSmoke) {
        Invoke-SuiteStep -Name "Bootstrap + RTX 5080 unified smoke" -Action {
            Invoke-CheckedNative -Executable "powershell.exe" -CommandArgs @(
                "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                (Join-Path $ProjectRoot "scripts\setup_and_smoke_unified_windows.ps1"),
                "-InstallRoot", $InstallRoot
            ) -WorkingDirectory $ProjectRoot
        }
    } else {
        if (-not $SkipBootstrap) {
            Invoke-SuiteStep -Name "Bootstrap unified runtime" -Action {
                Invoke-CheckedNative -Executable "powershell.exe" -CommandArgs @(
                    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                    (Join-Path $ProjectRoot "scripts\bootstrap_unified_runtime.ps1"),
                    "-InstallRoot", $InstallRoot,
                    "-InstallRustIfMissing", "-InstallBuildToolsIfMissing"
                ) -WorkingDirectory $ProjectRoot
            }
        }
        if (-not $SkipSmoke) {
            Invoke-SuiteStep -Name "RTX 5080 unified smoke" -Action {
                Invoke-CheckedNative -Executable "powershell.exe" -CommandArgs @(
                    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                    (Join-Path $ProjectRoot "scripts\smoke_unified_windows.ps1"),
                    "-InstallRoot", $InstallRoot
                ) -WorkingDirectory $ProjectRoot
            }
        }
    }

    if ($RunMode -in @("Experiment", "Full")) {
        Invoke-SuiteStep -Name "Experiment prerequisites" -Action { Assert-ExperimentPrerequisites }
        foreach ($mode in $SelectedModes) {
            foreach ($variant in @("mortal", "rogs", "rogs-global")) {
                Invoke-SuiteStep -Name "Train $mode $variant" -Action { Invoke-Ablation -Mode $mode -Variant $variant }
            }
            foreach ($variant in @("rogs", "rogs-global")) {
                Invoke-SuiteStep -Name "Compare $mode $variant vs mortal" -Action { Invoke-Comparison -Mode $mode -Variant $variant }
            }
        }
    }

    if ($RunMode -eq "Full" -and -not $SkipSoak) {
        Invoke-SuiteStep -Name "RTX serving production soak" -Action { Invoke-ServingSoak }
    }

    $gitSha = "unknown"
    try { $gitSha = ((& git -C $ProjectRoot rev-parse HEAD 2>$null) | Out-String).Trim() } catch {}
    $summary = [ordered]@{
        protocol = "mortal-rogs-local-workstation-suite-v1"
        ok = $true
        run_mode = $RunMode
        game_modes = $GameModes
        project_root = $ProjectRoot
        project_commit = $gitSha
        runtime_root = $InstallRoot
        device = $Device
        gpu = Get-GpuSnapshot
        training_seed = $TrainingSeed
        comparison_seed_start = $SeedStart
        comparison_seed_count = $SeedCount
        comparison_seed_key = $SeedKey
        rating_profile = $RatingProfile
        soak_minutes = if ($RunMode -eq "Full" -and -not $SkipSoak) { $SoakMinutes } else { 0 }
        steps = @($Steps)
        comparisons = @($Comparisons)
        results_root = $SuiteRoot
        completed_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    }
    $summaryPath = Join-Path $SuiteRoot "summary.json"
    $summary | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $summaryPath -Encoding UTF8

    Write-Host ""
    Write-Host "MORTAL_ROGS_LOCAL_SUITE_OK mode=$RunMode results=$SuiteRoot" -ForegroundColor Green
    Write-Host "Summary: $summaryPath"
    if ($OpenResults) { Start-Process explorer.exe -ArgumentList @($SuiteRoot) | Out-Null }
} catch {
    $failure = [ordered]@{
        protocol = "mortal-rogs-local-workstation-suite-v1"
        ok = $false
        run_mode = $RunMode
        game_modes = $GameModes
        runtime_root = $InstallRoot
        error = $_.Exception.Message
        steps = @($Steps)
        results_root = $SuiteRoot
        failed_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    }
    $failure | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $SuiteRoot "summary.json") -Encoding UTF8
    Write-Host "MORTAL_ROGS_LOCAL_SUITE_FAILED results=$SuiteRoot" -ForegroundColor Red
    throw
} finally {
    Stop-SoakServer
    try { Stop-Transcript | Out-Null } catch {}
}
