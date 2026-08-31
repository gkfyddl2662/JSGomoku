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
set CMD="%PY%" "%~dp0scripts\prepare_selfplay_population_compat.py" --runtime-root "%RUNTIME_ROOT%" --mode "%MODE%" --champion "%CHAMPION%" --trusted "%CHAMPION%" --candidate "%CHAMPION%" --device cuda:0 --gameplay-smoke
if not "%~4"=="" set CMD=!CMD! --candidate "%~4"
if not "%~5"=="" set CMD=!CMD! --candidate "%~5"
if not "%~6"=="" set CMD=!CMD! --candidate "%~6"
if not "%~7"=="" set CMD=!CMD! --candidate "%~7"

echo [Mortal-ROGS] Preparing %MODE% self-play population...
call !CMD!
if errorlevel 1 (
  echo [FAILED] Population preparation failed. Existing Mortal slots were not replaced.
  exit /b 1
)

echo [Mortal-ROGS] Installing validated Champion into compatible model slots...
"%PY%" "%~dp0scripts\install_population_champion.py" --runtime-root "%RUNTIME_ROOT%" --mode "%MODE%"
if errorlevel 1 (
  echo [FAILED] Champion installation failed.
  exit /b 1
)

echo [OK] Population prepared and Champion installed.
exit /b 0

:generate
if "%~2"=="" goto :help
set "MODE=%~2"
set "GAMES=%~3"
if "%GAMES%"=="" set "GAMES=1000"
set "ACTIVATE=%~4"
set CMD="%PY%" "%~dp0scripts\generate_population_selfplay.py" --runtime-root "%RUNTIME_ROOT%" --mode "%MODE%" --games "%GAMES%" --contexts-per-matchup 128 --device cuda:0 --compile --amp
if /I "%ACTIVATE%"=="activate" set CMD=!CMD! --activate

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
echo Prepare/validate checkpoints, create a population, and install the Champion:
echo   RUN_SELFPLAY_POPULATION.bat prepare 3p "D:\models\sanma.pth"
echo   RUN_SELFPLAY_POPULATION.bat prepare 4p "D:\models\verified-4p.pth" "D:\models\other-4p.pth"
echo.
echo The first checkpoint is the preferred trusted Champion, but it is still checked

echo against the compatible Mortal v4 ABI and a real evaluator smoke. Akagi-compatible

echo 775-channel 3P checkpoints use the pinned libriichi3p bridge and are kept out of

echo native 1010-channel training slots. Additional PTHs are accepted only if validation

echo passes. Native Champions are installed into current.pth, best_mortal.pth and

echo baseline.pth. Different existing slot files are backed up under models\bootstrap-backup.
echo.
echo Generate Mortal-native training logs from the validated population:
echo   RUN_SELFPLAY_POPULATION.bat generate 3p 1000
echo   RUN_SELFPLAY_POPULATION.bat generate 4p 1000 activate
echo.
echo Add "activate" to point Mortal + GRP dataset config at selfplay-population data.
echo Generated logs and copied model files stay under Mortal_Unified\runtime\MODE.
echo.
exit /b 2
