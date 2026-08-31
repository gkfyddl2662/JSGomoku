# Tenhou Houou one-command training preparation

This workflow prepares real 3P/4P training inputs for the unified Mortal-ROGS runtime and then optionally starts the fair Mortal/ROGS experiment or the complete RTX 5080 suite.

It deliberately reuses pinned external tools instead of embedding another Mahjong log stack:

- `Apricot-S/houou-logs` at `d4ca693771517b67172521f2bd76517500db4a6e`
  - sequential Tenhou Houou log ID fetch/download/export
  - 3P/4P filtering
  - local SQLite cache/resume
- `Mateces/tenhou-sanma-to-mjai` at `e0bd7bffe24227f97600c710cffa4490117b634a`
  - Tenhou 3P XML -> MJAI including `nukidora`
- `Jim137/mjlog2mjai` at `c133f7dbf61046feaf1af72369d9a44056807657`
  - Tenhou 4P XML -> MJAI

Downloaded game logs remain under `Mortal_Unified\runtime` and must not be redistributed.

## First practical run

The workstation validation has already proven the unified CUDA/BF16/torch.compile runtime. Prepare a modest real dataset first:

```powershell
.\RUN_TENHOU_FULL.bat prepare 5000 5000 accept 10000
```

Arguments are:

```text
mode  3p_log_limit  4p_log_limit  accept  grp_steps
```

The literal `accept` is required. It acknowledges the local-data/no-redistribution rule and that this tool starts only one Tenhou download session at a time.

The prepare command performs:

1. Reuses the existing `Mortal_Unified` runtime, or runs validation/bootstrap if it is missing.
2. Installs/clones the pinned downloader/converters into `runtime\tools\tenhou-prep`.
3. Fetches current-year Houou log IDs with the downloader's archive + recent modes.
4. Downloads 3P and 4P logs sequentially with the requested limits.
5. Validates and exports raw XML into the local Tenhou cache.
6. Converts 3P and 4P to gzip MJAI.
7. Creates a deterministic 95/5 train/validation split.
8. Probes prepared MJAI through the unified `libriichi` GameplayLoader.
9. Updates `config.3p.toml` / `config.4p.toml` dataset and GRP paths.
10. Creates `baseline.pth` from the already ABI-validated smoke checkpoint unless an explicit compatible checkpoint is supplied.
11. Trains mode-specific GRP until the requested saved-step target is reached.

The resulting layout is:

```text
Mortal_Unified\
  runtime\
    tenhou-cache\
      houou-current.db
      xml\
        3p\
        4p\
      prepare.json
    tools\
      tenhou-prep\
    3p\
      data\
        tenhou-houou\
          train\*.json.gz
          val\*.json.gz
      models\
        baseline.pth
        grp.pth
    4p\
      data\
        tenhou-houou\
          train\*.json.gz
          val\*.json.gz
      models\
        baseline.pth
        grp.pth
```

## Prepare and immediately run the A/B experiment

```powershell
.\RUN_TENHOU_FULL.bat experiment 5000 5000 accept 10000
```

After preparation it starts, with the same dataset and seed:

```text
3P: mortal -> rogs -> rogs-global -> duplicate comparisons
4P: mortal -> rogs -> rogs-global -> duplicate comparisons
```

## One command through the production soak

```powershell
.\RUN_TENHOU_FULL.bat full 5000 5000 accept 10000
```

This prepares the data/GRP, trains all variants, runs bidirectional duplicate comparisons and then executes the existing RTX 5080 serving soak.

Do not start with one million logs just to test the pipeline. A practical progression is:

```text
5k/mode      pipeline + initial learning check
100k/mode    meaningful first offline comparison
1M/mode      serious bootstrap run
3M+          expand only after the strength curve justifies it
```

The log limit is a target for the local XML cache. Re-running the tool reuses already exported XML/MJAI and downloads only the remaining amount where possible.

## Using a stronger external Mortal v4 baseline

Checkpoint file size is not treated as compatibility evidence. The Akagi-NG bundled 4-5 MB models and a roughly 90 MB user-trained Mortal checkpoint may use different serialization/model structures.

Use the existing checkpoint ABI probe before adopting any external model. `prepare_tenhou_training.py` accepts explicit mode-specific baselines:

```powershell
& "C:\Users\small\Downloads\Mortal_Unified\.venv\Scripts\python.exe" `
  .\scripts\prepare_tenhou_training.py `
  --runtime-root "C:\Users\small\Downloads\Mortal_Unified" `
  --modes both `
  --limit-3p 5000 `
  --limit-4p 5000 `
  --grp-steps 10000 `
  --baseline-3p "D:\models\sanma-v4.pth" `
  --baseline-4p "D:\models\model_v4_20240308_best_min.pth" `
  --accept-tenhou-log-terms
```

Each explicit baseline is run through `check_mortal_api_checkpoint.py` on CPU before it is copied to the runtime. An incompatible checkpoint is rejected regardless of file size.

If no explicit baseline is supplied, the tool uses the mode-specific checkpoint produced by the successful unified validation as a fixed test-play reference. This fallback is not claimed to be a strong playing model and does not initialize the Mortal network; it only satisfies canonical `train.py`'s fixed reference player requirement.

## Data-source scope

The built-in downloader follows `houou-logs`' current supported path: current-year Houou IDs via archive/recent FileIndex modes, then individual local log downloads. Historical `scrawYYYY.zip` archives are not assumed to be available because the downloader project documents that those archive URLs currently return 404.

If older locally obtained raw logs are added later, they should be imported through a separate local-data path rather than silently changing the downloader semantics.

## Safety and reproducibility

- No concurrent Tenhou sessions are started.
- Raw/downloaded game logs are excluded from the Git repository because they live under `Mortal_Unified\runtime`.
- Converter/downloader Git SHAs are recorded in `prepare.json`.
- 3P and 4P remain separate datasets/checkpoints.
- Train/validation assignment is deterministic from the raw log filename.
- Conversion failures are written to `conversion-errors.txt`; preparation stops if more than 5% fail.
- The existing fair ablation runner still isolates `mortal`, `rogs`, and `rogs-global` checkpoints and keeps their training seed identical.
