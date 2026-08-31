# Tenhou Houou one-command training preparation

This workflow prepares real 3P/4P MJAI training inputs for the unified Mortal-ROGS runtime and can optionally hand off to the existing fair Mortal/ROGS experiment or full RTX 5080 suite.

## Usage/authorization boundary

Tenhou's official raw-log page imposes restrictions beyond download rate limits. In particular, it states that logs may not be used to develop/apply products competing with Tenhou, and directs users to contact Tenhou support for general-mahjong applications. It also prohibits services that let an unspecified public download Tenhou logs.

Therefore the built-in network path is not an implicit license for cross-platform AI training. Use it only when you have permission for the intended application. The BAT launcher requires the literal argument `authorized` as an explicit local acknowledgement. Downloaded logs stay local and are never added to this Git repository.

The downloader also follows Tenhou's technical download rules through the pinned `houou-logs` implementation: one session, compressed downloads, cache/size checks, and the documented update interval.

## Pinned tools

The preparation layer reuses pinned tools rather than creating another scraper/parser stack:

- `Apricot-S/houou-logs` @ `d4ca693771517b67172521f2bd76517500db4a6e`
  - sequential Houou ID fetch/download/export
  - 3P/4P filtering
  - SQLite cache/resume
- `Mateces/tenhou-sanma-to-mjai` @ `e0bd7bffe24227f97600c710cffa4490117b634a`
  - Tenhou 3P XML -> MJAI including `nukidora`
- `Jim137/mjlog2mjai` @ `c133f7dbf61046feaf1af72369d9a44056807657`
  - Tenhou 4P XML -> MJAI

The ordinary Jim137 converter is used only for 4P because its converter explicitly does not support Sanma. 3P uses the dedicated converter instead.

## First practical run

After you have permission for the intended use, prepare a modest dataset first:

```powershell
.\RUN_TENHOU_FULL.bat prepare 5000 5000 authorized 10000
```

Arguments:

```text
mode  3p_log_limit  4p_log_limit  authorized  grp_steps
```

The prepare command performs:

1. Reuses `Mortal_Unified`, or runs the existing validation/bootstrap if it is missing.
2. Installs/clones the pinned downloader/converters under `runtime\tools\tenhou-prep`.
3. Fetches the downloader's current-year archive + recent Houou FileIndex ranges.
4. Downloads 3P and 4P logs sequentially with the requested limits.
5. Validates and exports raw XML into the local Tenhou cache.
6. Converts 3P/4P separately to gzip MJAI.
7. Creates a deterministic 95/5 train/validation split.
8. Validates sample files through both unified `GameplayLoader` and the GRP loader and checks the player count.
9. Updates `config.3p.toml` / `config.4p.toml` dataset/GRP paths and invalidates stale file indexes.
10. Validates or creates a fixed `baseline.pth` reference.
11. Trains the mode-specific GRP to the requested saved-step target; an existing compatible GRP below the target is resumed.
12. Writes a preparation manifest containing the tool pins and per-mode inputs.

Result layout:

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
      data\tenhou-houou\
        train\*.json.gz
        val\*.json.gz
      models\
        baseline.pth
        grp.pth
    4p\
      data\tenhou-houou\
        train\*.json.gz
        val\*.json.gz
      models\
        baseline.pth
        grp.pth
```

## Prepare and immediately run the fair A/B experiment

```powershell
.\RUN_TENHOU_FULL.bat experiment 5000 5000 authorized 10000
```

After preparation this hands off to the existing runner:

```text
3P: mortal -> rogs -> rogs-global -> bidirectional duplicate comparisons
4P: mortal -> rogs -> rogs-global -> bidirectional duplicate comparisons
```

All variants keep the same base dataset and training seed while their output directories remain isolated.

## Dataset growth

Do not jump directly to a huge request simply to prove the pipeline. A practical research progression is:

```text
5k/mode      pipeline + initial-learning check
100k/mode    meaningful first offline comparison, if available/authorized
larger       expand only after the strength curve justifies it
```

The current built-in `houou-logs fetch` path covers the current year's archive/recent FileIndex ranges. It must not be presented as a guaranteed one-million-game historical downloader. The project's documented legacy `scrawYYYY.zip` URLs currently return 404, so multi-year historical acquisition requires a separately authorized/available historical source/import path rather than silently changing the downloader semantics.

## Using a stronger external Mortal v4 baseline

Checkpoint file size is not compatibility evidence. A 4-5 MB bundled Akagi model and a roughly 90 MB user-trained Mortal checkpoint may use different network or serialization formats.

The preparation script accepts explicit mode-specific Mortal v4 reference checkpoints:

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

Only run the network-download form after obtaining permission for the intended use. Each supplied checkpoint is run through `check_mortal_api_checkpoint.py` on CPU before it is copied into the runtime. An incompatible checkpoint is rejected regardless of file size.

If no explicit baseline is supplied, the tool uses the mode-specific checkpoint produced by the successful unified validation as a fixed test-play reference. That fallback is not claimed to be a strong model and does not initialize the trainable Mortal network; it only supplies canonical `train.py`'s fixed reference player.

## Reproducibility/scope

- 3P and 4P datasets/checkpoints remain separate.
- Downloader/converter Git SHAs are recorded in `prepare.json`.
- Train/validation assignment is deterministic from the raw log filename.
- Conversion errors are written to `conversion-errors.txt`; preparation stops if the failure ratio exceeds 5%.
- Prepared MJAI is checked by the same unified native loaders later used by Mortal/GRP training.
- No new experiment DB/server/service was introduced; the existing training/comparison/soak runners are reused.
