@echo off
setlocal EnableExtensions

set "MODE=%~1"
if "%MODE%"=="" set "MODE=validate"
set "POLICY=%~2"
if "%POLICY%"=="" set "POLICY=error"
set "GAMEMODES=%~3"
if "%GAMEMODES%"=="" set "GAMEMODES=both"

if /I "%MODE%"=="help" goto :help
if /I "%MODE%"=="-h" goto :help
if /I "%MODE%"=="--help" goto :help

if /I "%MODE%"=="validate" (
  set "RUNMODE=Validate"
) else if /I "%MODE%"=="experiment" (
  set "RUNMODE=Experiment"
) else if /I "%MODE%"=="full" (
  set "RUNMODE=Full"
) else (
  echo [ERROR] Unknown mode: %MODE%
  goto :help_error
)

if /I not "%POLICY%"=="error" if /I not "%POLICY%"=="fresh" if /I not "%POLICY%"=="resume" (
  echo [ERROR] Existing policy must be error, fresh, or resume: %POLICY%
  goto :help_error
)

if /I not "%GAMEMODES%"=="both" if /I not "%GAMEMODES%"=="3p" if /I not "%GAMEMODES%"=="4p" (
  echo [ERROR] Game modes must be both, 3p, or 4p: %GAMEMODES%
  goto :help_error
)

echo.
echo Mortal-ROGS local workstation suite
echo   mode     = %RUNMODE%
echo   existing = %POLICY%
echo   games    = %GAMEMODES%
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_local_workstation.ps1" -RunMode "%RUNMODE%" -ExistingPolicy "%POLICY%" -GameModes "%GAMEMODES%" -OpenResults
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo [FAILED] Mortal-ROGS local suite exited with code %RC%.
  exit /b %RC%
)

echo.
echo [OK] Mortal-ROGS local suite completed.
exit /b 0

:help
echo Usage:
echo   RUN_LOCAL.bat validate
echo   RUN_LOCAL.bat experiment [error^|fresh^|resume] [both^|3p^|4p]
echo   RUN_LOCAL.bat full       [error^|fresh^|resume] [both]
echo.
echo Examples:
echo   RUN_LOCAL.bat validate
echo   RUN_LOCAL.bat experiment fresh both
echo   RUN_LOCAL.bat experiment resume 3p
echo   RUN_LOCAL.bat full fresh both
echo.
echo Advanced options are available through scripts\run_local_workstation.ps1.
exit /b 0

:help_error
call :help
exit /b 2
