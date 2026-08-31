@echo off
setlocal EnableExtensions

set "MODE=%~1"
if "%MODE%"=="" set "MODE=prepare"
set "LIMIT3=%~2"
if "%LIMIT3%"=="" set "LIMIT3=5000"
set "LIMIT4=%~3"
if "%LIMIT4%"=="" set "LIMIT4=5000"
set "TERMS=%~4"
set "GRPSTEPS=%~5"
if "%GRPSTEPS%"=="" set "GRPSTEPS=10000"

if /I not "%MODE%"=="prepare" if /I not "%MODE%"=="experiment" if /I not "%MODE%"=="full" goto :help_error
if /I not "%TERMS%"=="authorized" (
  echo [ERROR] Tenhou training downloads require the literal argument: authorized
  echo         Use it only if you have permission for the intended training/application.
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
echo Mortal-ROGS Tenhou training preparation
echo   mode      = %MODE%
echo   3p logs   = %LIMIT3%
echo   4p logs   = %LIMIT4%
echo   GRP steps = %GRPSTEPS%
echo   runtime   = %RUNTIME%
echo.
echo Tenhou logs stay local. Do not redistribute downloaded log data.
echo Only one Tenhou download session is started by this tool.
echo 'authorized' means you have permission for this intended use under Tenhou's terms.
echo.

"%PY%" "%PROJECT%scripts\prepare_tenhou_training.py" ^
  --runtime-root "%RUNTIME%" ^
  --modes both ^
  --limit-3p "%LIMIT3%" ^
  --limit-4p "%LIMIT4%" ^
  --grp-steps "%GRPSTEPS%" ^
  --accept-tenhou-log-terms
if errorlevel 1 (
  echo.
  echo [FAILED] Tenhou training preparation failed.
  exit /b 1
)

if /I "%MODE%"=="prepare" (
  echo.
  echo [OK] Tenhou data, baseline reference and GRP preparation completed.
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
echo [OK] Mortal-ROGS Tenhou %MODE% pipeline completed.
exit /b 0

:help
echo PowerShell usage:
echo   .\RUN_TENHOU_FULL.bat prepare    [3p_limit] [4p_limit] authorized [grp_steps]
echo   .\RUN_TENHOU_FULL.bat experiment [3p_limit] [4p_limit] authorized [grp_steps]
echo   .\RUN_TENHOU_FULL.bat full       [3p_limit] [4p_limit] authorized [grp_steps]
echo.
echo Examples ^(only after obtaining permission for the intended use^):
echo   .\RUN_TENHOU_FULL.bat prepare 5000 5000 authorized 10000
echo   .\RUN_TENHOU_FULL.bat experiment 100000 100000 authorized 20000
echo.
echo The literal 'authorized' confirms that you have permission for this use,
echo downloaded logs remain local, are not redistributed, and one session is used.
echo Tenhou's raw-log page states additional restrictions on competing/general mahjong applications.
echo For custom baseline checkpoints, call scripts\prepare_tenhou_training.py directly.
exit /b 0

:help_error
call :help
exit /b 2
