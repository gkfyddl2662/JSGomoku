param(
    [string]$RuntimeRoot = "$PSScriptRoot\..\..\Mortal_ROGS_Runtime",
    [string]$Mortal3PRoot = "",
    [string]$Mortal4PRoot = "",
    [switch]$SkipCompile,
    [switch]$SkipTrainingStep,
    [switch]$SkipWebUI
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
$RuntimeRoot = [System.IO.Path]::GetFullPath($RuntimeRoot)
if (-not $Mortal3PRoot) { $Mortal3PRoot = Join-Path $RuntimeRoot "3p" }
if (-not $Mortal4PRoot) { $Mortal4PRoot = Join-Path $RuntimeRoot "4p" }
$Mortal3PRoot = [System.IO.Path]::GetFullPath($Mortal3PRoot)
$Mortal4PRoot = [System.IO.Path]::GetFullPath($Mortal4PRoot)
$Py3 = "$Mortal3PRoot\.venv\Scripts\python.exe"
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
    [string]$RuntimePath
) {
    Assert-File $Python "$Mode Python"
    $probeArgs = @($Probe, "--mode", $Mode, "--runtime-root", $RuntimePath)
    if ($SkipCompile) { $probeArgs += "--skip-compile" }
    if ($SkipTrainingStep) { $probeArgs += "--skip-training-step" }

    Write-Host ""
    Write-Host "=== Mortal $Mode isolated runtime smoke ===" -ForegroundColor Cyan
    & $Python @probeArgs
    if ($LASTEXITCODE -ne 0) {
        throw "$Mode runtime smoke failed with exit code $LASTEXITCODE"
    }
}

Write-Host "Unified runtime root: $RuntimeRoot"
Assert-File $Probe "Runtime smoke probe"
Invoke-RuntimeSmoke -Mode "3p" -Python $Py3 -RuntimePath $Mortal3PRoot
Invoke-RuntimeSmoke -Mode "4p" -Python $Py4 -RuntimePath $Mortal4PRoot

if (-not $SkipWebUI) {
    Write-Host ""
    Write-Host "=== Control Center API routing smoke ===" -ForegroundColor Cyan
    $env:MORTAL_RUNTIME_ROOT = $RuntimeRoot
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
            $startArgs = @{
                FilePath = $Py3
                ArgumentList = @("-m", "app.main")
                WorkingDirectory = $ProjectRoot
                PassThru = $true
                WindowStyle = "Hidden"
            }
            $proc = Start-Process @startArgs
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
