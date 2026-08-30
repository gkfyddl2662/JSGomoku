param(
    [string]$Mortal3PRoot = "$PSScriptRoot\..\..\Mortal_Sanma",
    [string]$Mortal4PRoot = "$PSScriptRoot\..\..\Mortal_4P",
    [switch]$SkipCompile,
    [switch]$SkipTrainingStep,
    [switch]$SkipWebUI
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
$Mortal3PRoot = [System.IO.Path]::GetFullPath($Mortal3PRoot)
$Mortal4PRoot = [System.IO.Path]::GetFullPath($Mortal4PRoot)
$Py3 = "$ProjectRoot\.venv\Scripts\python.exe"
$Py4 = "$Mortal4PRoot\.venv\Scripts\python.exe"
$Probe = "$ProjectRoot\scripts\smoke_runtime.py"

function Assert-File([string]$Path, [string]$Label) {
    if (-not (Test-Path $Path -PathType Leaf)) {
        throw "$Label missing: $Path"
    }
}

function Invoke-RuntimeSmoke(
    [string]$Mode,
    [string]$Python,
    [string]$RuntimeRoot
) {
    Assert-File $Python "$Mode Python"
    $args = @($Probe, "--mode", $Mode, "--runtime-root", $RuntimeRoot)
    if ($SkipCompile) { $args += "--skip-compile" }
    if ($SkipTrainingStep) { $args += "--skip-training-step" }

    Write-Host ""
    Write-Host "=== Mortal $Mode isolated runtime smoke ===" -ForegroundColor Cyan
    & $Python @args
    if ($LASTEXITCODE -ne 0) {
        throw "$Mode runtime smoke failed with exit code $LASTEXITCODE"
    }
}

Assert-File $Probe "Runtime smoke probe"
Invoke-RuntimeSmoke -Mode "3p" -Python $Py3 -RuntimeRoot $Mortal3PRoot
Invoke-RuntimeSmoke -Mode "4p" -Python $Py4 -RuntimeRoot $Mortal4PRoot

if (-not $SkipWebUI) {
    Write-Host ""
    Write-Host "=== Control Center API routing smoke ===" -ForegroundColor Cyan
    $env:MORTAL_3P_ROOT = $Mortal3PRoot
    $env:MORTAL_4P_ROOT = $Mortal4PRoot
    $env:PYTHONPATH = $ProjectRoot

    $base = "http://127.0.0.1:8188"
    $started = $false
    $proc = $null

    try {
        $existing = $null
        try {
            $existing = Invoke-RestMethod -Uri "$base/api/setup/status/all" -TimeoutSec 2
        } catch {
            # Start a temporary Control Center instance only when the port is not already serving it.
        }

        if ($null -eq $existing) {
            $proc = Start-Process \
                -FilePath $Py3 \
                -ArgumentList @("-m", "app.main") \
                -WorkingDirectory $ProjectRoot \
                -PassThru \
                -WindowStyle Hidden
            $started = $true

            $deadline = (Get-Date).AddSeconds(30)
            do {
                Start-Sleep -Milliseconds 500
                try {
                    $existing = Invoke-RestMethod -Uri "$base/api/setup/status/all" -TimeoutSec 2
                } catch {
                    if ($proc.HasExited) {
                        throw "Control Center exited before becoming ready (exit $($proc.ExitCode))"
                    }
                }
            } while ($null -eq $existing -and (Get-Date) -lt $deadline)
        }

        if ($null -eq $existing) {
            throw "Control Center did not answer $base/api/setup/status/all"
        }
        if (-not $existing.'3p'.ready) {
            throw "Control Center reports 3p runtime not ready: $($existing.'3p'.checks | ConvertTo-Json -Compress)"
        }
        if (-not $existing.'4p'.ready) {
            throw "Control Center reports 4p runtime not ready: $($existing.'4p'.checks | ConvertTo-Json -Compress)"
        }

        $cfg3 = Invoke-RestMethod -Uri "$base/api/config?mode=3p" -TimeoutSec 5
        $cfg4 = Invoke-RestMethod -Uri "$base/api/config?mode=4p" -TimeoutSec 5
        if ($cfg3.mode -ne "3p") { throw "3p config route returned mode=$($cfg3.mode)" }
        if ($cfg4.mode -ne "4p") { throw "4p config route returned mode=$($cfg4.mode)" }
        if ($cfg3.path -eq $cfg4.path) { throw "3p and 4p config routes resolved to the same path" }

        $data3 = Invoke-RestMethod -Uri "$base/api/data?mode=3p" -TimeoutSec 5
        $data4 = Invoke-RestMethod -Uri "$base/api/data?mode=4p" -TimeoutSec 5
        if ($data3.mode -ne "3p" -or $data4.mode -ne "4p") {
            throw "Data API mode routing failed"
        }

        Write-Host "CONTROL_CENTER_DUAL_RUNTIME_OK" -ForegroundColor Green
        Write-Host "3p config: $($cfg3.path)"
        Write-Host "4p config: $($cfg4.path)"
    } finally {
        if ($started -and $null -ne $proc -and -not $proc.HasExited) {
            Stop-Process -Id $proc.Id -Force
        }
    }
}

Write-Host ""
Write-Host "WINDOWS_DUAL_RUNTIME_SMOKE_OK" -ForegroundColor Green
Write-Host "Both isolated libriichi ABIs, RTX CUDA/BF16, Mortal forward/backward, and Control Center routing passed."
