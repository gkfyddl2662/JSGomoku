@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"
set "RUNTIME_ROOT=%~dp0..\Mortal_Unified"
set "PY=%RUNTIME_ROOT%\.venv\Scripts\python.exe"

if not exist "%PY%" (
  echo [FAILED] Unified runtime Python not found: "%PY%"
  exit /b 1
)

if /I "%~1"=="prepare" goto :prepare
if /I "%~1"=="generate" goto :generate
if /I "%~1"=="help" goto :help
if "%~1"=="" goto :help

echo [FAILED] Unknown command: %~1
goto :help

:prepare
if "%~2"=="" goto :help
if "%~3"=="" goto :help
set "MODE=%~2"
set "CHAMPION=%~3"
set "CMD="%PY%" "%~dp0scripts\prepare_selfplay_population.py" --runtime-root "%RUNTIME_ROOT%" --mode "%MODE%" --champion "%CHAMPION%" --trusted "%CHAMPION%" --candidate "%CHAMPION%" --device cuda:0 --gameplay-smoke"
if not "%~4"=="" set "CMD=!CMD! --candidate "%~4""
if not "%~5"=="" set "CMD=!CMD! --candidate "%~5""
if not "%~6"=="" set "CMD=!CMD! --candidate "%~6""
if not "%~7"=="" set "CMD=!CMD! --candidate "%~7""

echo [Mortal-ROGS] Preparing %MODE% self-play population...
call !CMD!
if errorlevel 1 (
  echo [FAILED] Population preparation failed.
  exit /b 1
)
echo [OK] Population prepared.
exit /b 0

:generate
if "%~2"=="" goto :help
set "MODE=%~2"
set "GAMES=%~3"
if "%GAMES%"=="" set "GAMES=1000"
set "ACTIVATE=%~4"
set "CMD="%PY%" "%~dp0scripts\generate_population_selfplay.py" --runtime-root "%RUNTIME_ROOT%" --mode "%MODE%" --games "%GAMES%" --contexts-per-matchup 32 --device cuda:0 --compile --amp"
if /I "%ACTIVATE%"=="activate" set "CMD=!CMD! --activate"

echo [Mortal-ROGS] Generating %GAMES%+ %MODE% self-play game logs...
call !CMD!
if errorlevel 1 (
  echo [FAILED] Population self-play generation failed.
  exit /b 1
)
echo [OK] Self-play dataset generated.
exit /b 0

:help
echo.
echo Mortal-ROGS Population Self-play
echo.
echo Prepare/validate checkpoints and create a mode-specific population:
echo   RUN_SELFPLAY_POPULATION.bat prepare 3p "D:\models\sanma.pth"
echo   RUN_SELFPLAY_POPULATION.bat prepare 4p "D:\models\verified-4p.pth" "D:\models\other-4p.pth"
echo.
echo The first checkpoint is treated as the preferred trusted Champion, but it is

echo still checked against the current Mortal v4 ABI and gameplay evaluator.
echo Additional checkpoints are accepted only if validation passes.
echo.
echo Generate Mortal-native training logs from the validated population:
echo   RUN_SELFPLAY_POPULATION.bat generate 3p 1000
echo   RUN_SELFPLAY_POPULATION.bat generate 4p 1000 activate
echo.
echo Add "activate" to point Mortal + GRP dataset config at self-play-population data.
echo Generated logs and copied model files stay under Mortal_Unified\runtime\MODE.
echo.
exit /b 2
