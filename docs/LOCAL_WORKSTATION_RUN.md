# Local workstation one-command run

`RUN_LOCAL.bat` is the Windows entrypoint for the local RTX 5080 validation/experiment workflow. It wraps the existing unified bootstrap, smoke, training ablation, Mortal-style model comparison, Akagi inference service, and serving soak scripts instead of introducing a separate experiment service.

## 1. Validate the workstation first

From the Mortal-ROGS project root:

```bat
RUN_LOCAL.bat validate
```

This is safe to use on a fresh machine/runtime. It:

1. Creates or refreshes the pinned unified Mortal runtime.
2. Installs Rust/MSVC Build Tools when missing.
3. Installs the RTX 5080 Python/CUDA/Triton stack.
4. Applies the unified 3P/4P patches.
5. Builds the single PyO3 `libriichi` extension.
6. Runs the CUDA/BF16/`torch.compile` runtime smoke.
7. Runs real 3P/4P gameplay, native log reload, real-data mini-training, evaluator, Akagi HTTP API, and Control Center routing smoke tests.

Default runtime location is the `Mortal_Unified` directory next to this repository.

## 2. Prepare real experiment inputs

`experiment` and `full` intentionally refuse to invent production training inputs. For every selected mode, prepare:

```text
Mortal_Unified\runtime\3p\data\**\*.json.gz
Mortal_Unified\runtime\3p\models\baseline.pth
Mortal_Unified\runtime\3p\models\grp.pth

Mortal_Unified\runtime\4p\data\**\*.json.gz
Mortal_Unified\runtime\4p\models\baseline.pth
Mortal_Unified\runtime\4p\models\grp.pth
```

The bootstrap preserves the `runtime` directory, so real datasets and model files remain in place when the canonical Mortal source is refreshed and patched again.

The tool fails during preflight before starting long training if any required input is absent.

## 3. Run the fair Mortal/ROGS experiment

Start fresh isolated runs for both modes:

```bat
RUN_LOCAL.bat experiment fresh both
```

This performs, for 3P and then 4P:

```text
mortal
rogs
rogs-global
```

All three variants use the same base config and training seed. Their checkpoints, TensorBoard data, and test logs are isolated.

After training, it automatically runs:

```text
rogs        <-> mortal
rogs-global <-> mortal
```

using the same duplicate seed range in both directions. 3P rotates ABC and 4P rotates ABCD. The comparison emits paired JSONL, Mortal-style strength JSON/Markdown, native `libriichi.Stat` reports, and `comparison.json`.

Existing run policy:

```bat
RUN_LOCAL.bat experiment error both
RUN_LOCAL.bat experiment fresh both
RUN_LOCAL.bat experiment resume both
```

- `error` is the default and prevents accidental reuse/overwrite.
- `fresh` deletes only the isolated ablation output for the selected seed/variant before retraining.
- `resume` explicitly resumes the existing isolated checkpoint.

Single-mode experiments are supported:

```bat
RUN_LOCAL.bat experiment fresh 3p
RUN_LOCAL.bat experiment fresh 4p
```

## 4. Run the complete workstation suite including the real RTX serving gate

```bat
RUN_LOCAL.bat full fresh both
```

`full` executes validation + all three training variants + bidirectional duplicate comparisons, then starts the actual Mortal Akagi inference API and runs the production serving soak.

Default soak parameters:

- 30 minutes
- mixed 3P/4P traffic
- concurrency 8
- batch rows 1
- required `nvidia-smi` GPU telemetry
- production gate failure causes the command to fail

For the serving models, the suite prefers the newly trained `rogs-global` checkpoint for each mode. If it is unavailable it falls back to that mode's `best_mortal.pth`.

A non-skipped production soak requires `both` modes because the API's global health covers both model slots.

## Advanced PowerShell options

Use the PowerShell entrypoint directly when changing experiment parameters:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_local_workstation.ps1 `
  -RunMode Full `
  -GameModes both `
  -ExistingPolicy fresh `
  -TrainingSeed 36887 `
  -SeedStart 10000 `
  -SeedCount 1000 `
  -SeedKey "0xD5DFAA4CEF265CD7" `
  -Device cuda:0 `
  -SoakMinutes 30 `
  -SoakConcurrency 8 `
  -SoakBatchRows 1 `
  -OpenResults
```

Useful switches:

```text
-SkipBootstrap
-SkipSmoke
-SkipSoak
-OpenResults
```

`SeedKey` is a string on purpose. Mortal's `0xD5DFAA4CEF265CD7` seed key exceeds JavaScript's safe integer range and must not be rounded.

## Results

Results are deliberately stored outside both the project Git tree and `Mortal_Unified` so a fresh bootstrap cannot mistake a results directory for a partially created Mortal clone.

Default location:

```text
<workspace>\Mortal_ROGS_Results\YYYYMMDD-HHMMSS-validate\
<workspace>\Mortal_ROGS_Results\YYYYMMDD-HHMMSS-experiment\
<workspace>\Mortal_ROGS_Results\YYYYMMDD-HHMMSS-full\
```

Each run contains at least:

```text
local-suite.log
summary.json
```

Experiment runs additionally contain per-mode comparison directories. Full runs additionally contain:

```text
serving-soak.json
inference.stdout.log
inference.stderr.log
```

The final success marker is:

```text
MORTAL_ROGS_LOCAL_SUITE_OK
```

If a step fails, `summary.json` records the failed step and error and the command exits non-zero.

## Statistical note

The default comparison seed count is 100 for a practical first local run. It is a preview, not a claim of model superiority. For a real promotion decision, increase the duplicate sample until the paired bootstrap confidence interval is sufficiently stable. Mortal's own strength comparisons use very large duplicate samples when distinguishing small model differences.
