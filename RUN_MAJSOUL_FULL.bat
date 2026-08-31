@echo off
setlocal EnableExtensions

set "MODE=%~1"
if "%MODE%"=="" set "MODE=prepare"
set "LIMIT3=%~2"
if "%LIMIT3%"=="" set "LIMIT3=5000"
set "LIMIT4=%~3"
if "%LIMIT4%"=="" set "LIMIT4=5000"
set "AUTH=%~4"
set "GRPSTEPS=%~5"
if "%GRPSTEPS%"=="" set "GRPSTEPS=10000"
set "SERVER=%~6"
if "%SERVER%"=="" set "SERVER=cn"

if /I not "%MODE%"=="prepare" if /I not "%MODE%"=="experiment" if /I not "%MODE%"=="full" goto :help_error
if /I not "%AUTH%"=="authorized" (
  echo [ERROR] Mahjong Soul preparation requires the literal argument: authorized
  echo         Use it only for records you are permitted to access and keep downloaded records local.
  goto :help_error
)

set "PROJECT=%~dp0"
for %%I in ("%PROJECT%..") do set "WORKSPACE=%%~fI"
set "RUNTIME=%WORKSPACE%\Mortal_Unified"
set "PY=%RUNTIME%\.venv\Scripts\python.exe"

if not exist "%PY%" (
  echo [INFO] Unified runtime is missing. Running workstation validation/bootstrap first...
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PROJECT%scripts\run_local_workstation.ps1" -RunMode Validate -GameModes both
  if errorlevel 1 exit /b 1
)

echo.
echo Mortal-ROGS Mahjong Soul training preparation
echo   mode      = %MODE%
echo   3p target = %LIMIT3%
echo   4p target = %LIMIT4%
echo   GRP steps = %GRPSTEPS%
echo   server    = %SERVER%
echo   runtime   = %RUNTIME%
echo.
echo Credentials are requested interactively by Python and are not written to project configs or manifests.
echo Downloaded Mahjong Soul records remain local and must not be redistributed.
echo.

"%PY%" "%PROJECT%scripts\prepare_majsoul_training.py" ^
  --runtime-root "%RUNTIME%" ^
  --modes both ^
  --limit-3p "%LIMIT3%" ^
  --limit-4p "%LIMIT4%" ^
  --grp-steps "%GRPSTEPS%" ^
  --server "%SERVER%" ^
  --api-rps 4 ^
  --download-delay-ms 300 ^
  --authorized-local-use
if errorlevel 1 (
  echo.
  echo [FAILED] Mahjong Soul training preparation failed.
  exit /b 1
)

if /I "%MODE%"=="prepare" (
  echo.
  echo [OK] Mahjong Soul data, baseline reference and GRP preparation completed.
  exit /b 0
)

if /I "%MODE%"=="experiment" set "RUNMODE=Experiment"
if /I "%MODE%"=="full" set "RUNMODE=Full"

powershell.exe -NoProfile -ExecutionPolicy Bypass ^
  -File "%PROJECT%scripts\run_local_workstation.ps1" ^
  -RunMode "%RUNMODE%" ^
  -GameModes both ^
  -ExistingPolicy fresh ^
  -SkipBootstrap ^
  -SkipSmoke ^
  -OpenResults
if errorlevel 1 (
  echo.
  echo [FAILED] Mortal-ROGS %MODE% run failed.
  exit /b 1
)

echo.
echo [OK] Mortal-ROGS Mahjong Soul %MODE% pipeline completed.
exit /b 0

:help
echo PowerShell usage:
echo   .\RUN_MAJSOUL_FULL.bat prepare    [3p_target] [4p_target] authorized [grp_steps] [server]
echo   .\RUN_MAJSOUL_FULL.bat experiment [3p_target] [4p_target] authorized [grp_steps] [server]
echo   .\RUN_MAJSOUL_FULL.bat full       [3p_target] [4p_target] authorized [grp_steps] [server]
echo.
echo server: cn ^| en ^| jp   ^(default: cn^)
echo.
echo The downloader prioritizes high-rank rooms and prompts for a native Mahjong Soul account/password.
echo Credentials are runtime-only; downloaded game records remain local and must not be redistributed.
echo For custom date/RPS/baseline controls, call scripts\prepare_majsoul_training.py directly.
exit /b 0

:help_error
call :help
exit /b 2
