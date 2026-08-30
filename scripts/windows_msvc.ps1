function Import-MortalRogsVsDevEnvironment {
    $programFilesX86 = ${env:ProgramFiles(x86)}
    if ([string]::IsNullOrWhiteSpace($programFilesX86)) {
        return $false
    }
    $vswhere = Join-Path $programFilesX86 "Microsoft Visual Studio\Installer\vswhere.exe"
    if (-not (Test-Path $vswhere)) {
        return $false
    }

    $installationPath = (& $vswhere `
        -latest `
        -products * `
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
        -property installationPath | Select-Object -First 1)
    if ([string]::IsNullOrWhiteSpace($installationPath)) {
        return $false
    }

    $devCmd = Join-Path $installationPath "Common7\Tools\VsDevCmd.bat"
    if (-not (Test-Path $devCmd)) {
        return $false
    }

    $cmdLine = "`"$devCmd`" -no_logo -arch=x64 -host_arch=x64 >nul && set"
    $environmentLines = @(& cmd.exe /d /s /c $cmdLine)
    if ($LASTEXITCODE -ne 0) {
        return $false
    }

    foreach ($line in $environmentLines) {
        $eq = $line.IndexOf('=')
        if ($eq -le 0) { continue }
        $name = $line.Substring(0, $eq)
        $value = $line.Substring($eq + 1)
        [Environment]::SetEnvironmentVariable($name, $value, 'Process')
    }
    return $true
}

function Test-MortalRogsRustMsvcLink {
    if (-not (Get-Command rustc -ErrorAction SilentlyContinue)) {
        return $false
    }
    $probeRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("mortal-rogs-msvc-probe-" + [Guid]::NewGuid().ToString('N'))
    $source = Join-Path $probeRoot "main.rs"
    $exe = Join-Path $probeRoot "probe.exe"
    New-Item -ItemType Directory -Path $probeRoot -Force | Out-Null
    try {
        [System.IO.File]::WriteAllText($source, 'fn main() { println!("ok"); }' + [Environment]::NewLine)
        & rustc $source -o $exe *> $null
        return $LASTEXITCODE -eq 0 -and (Test-Path $exe)
    } finally {
        Remove-Item -LiteralPath $probeRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Ensure-MortalRogsMsvcBuildEnvironment {
    param(
        [switch]$InstallIfMissing
    )

    Import-MortalRogsVsDevEnvironment | Out-Null
    if (Test-MortalRogsRustMsvcLink) {
        Write-Host "MSVC_LINK_PROBE_OK"
        return
    }

    if (-not $InstallIfMissing) {
        throw @"
Rust MSVC link probe failed. Visual Studio C++ Build Tools / Windows SDK are required.
Rerun bootstrap with -InstallBuildToolsIfMissing, or install them with:
winget install --id Microsoft.VisualStudio.2022.BuildTools --exact --source winget --force --override "--wait --passive --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
"@
    }

    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "winget is unavailable; install Visual Studio Build Tools with the C++ workload and Windows SDK, then rerun."
    }

    Write-Host "Installing Visual Studio 2022 Build Tools C++ workload..."
    & winget install `
        --id Microsoft.VisualStudio.2022.BuildTools `
        --exact `
        --source winget `
        --force `
        --accept-package-agreements `
        --accept-source-agreements `
        --override "--wait --passive --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
    $installExit = $LASTEXITCODE

    Import-MortalRogsVsDevEnvironment | Out-Null
    if (-not (Test-MortalRogsRustMsvcLink)) {
        throw "MSVC link probe still fails after Build Tools installation (winget exit $installExit). A Windows restart may be required, or verify the C++ workload and Windows SDK in Visual Studio Installer."
    }

    Write-Host "MSVC_LINK_PROBE_OK"
}
