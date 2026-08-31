# Mahjong Soul training preparation

This path prepares local Mahjong Soul ranked-game records for Mortal-ROGS without publishing or bundling game-log data.

## Data path

The preparation flow is:

```text
Amae-Koromo metadata API
  -> recent high-rank game UUID discovery
  -> Mahjong Soul authenticated game-record download
  -> raw protobuf
  -> pinned Majsoul-to-MJAI converter
  -> deterministic train/validation split
  -> unified libriichi GameplayLoader + GRP validation
  -> mode-specific GRP preparation
  -> existing Mortal / ROGS / ROGS+Global experiment runner
```

The downloader prioritizes higher rooms and only falls back when the requested local target is not reached.

- 4P: Throne -> Jade -> Gold.
- 3P: Sanma Throne -> Sanma Jade -> Sanma Gold.
- 3P uses the Amae-Koromo `pl3` API family.
- 4P uses the Amae-Koromo `pl4` API family.
- API windows are subdivided automatically when a response reaches the server-side record cap, so the tool does not silently truncate a busy interval.
- Completed room/day discovery windows are journaled locally, so increasing a target does not needlessly rescan completed windows.

The external converter/downloader is pinned to:

```text
NikkeTryHard/tenhou-to-mjai
69fb75a51c7efef3212be603227b2a58a9717237
```

Its Majsoul converter emits `nukidora` for 3P north-tile extraction and supports both three- and four-player MJAI output.

## Local-data policy

Use this tool only for records you are permitted to access. Downloaded Mahjong Soul records stay local and must not be redistributed.

The repository contains tooling only. It does not contain, publish, mirror, or describe a pre-built Mahjong Soul game-log dataset.

The generated local manifest records source/provenance and preparation configuration but does not store the account password.

## Credentials

Use the PowerShell-visible batch launcher:

```powershell
.\RUN_MAJSOUL_FULL.bat prepare <3p_target> <4p_target> authorized <grp_steps> cn
```

The Python preparation process prompts for a native Mahjong Soul account and password. The password is held only in memory for the local download process.

The password is not written to:

- Git;
- Mortal TOML files;
- experiment manifests;
- result summaries.

The pinned Rust downloader currently accepts its password as a child-process argument, so it can be transiently visible to local process-inspection tools while that child process is running. It is not logged by the Mortal-ROGS wrapper.

For non-interactive local execution, set `MORTAL_ROGS_MAJSOUL_USERNAME` and `MORTAL_ROGS_MAJSOUL_PASSWORD`, call `scripts/prepare_majsoul_training.py` directly, and clear the variables after the run. `--username` is also accepted, but there is intentionally no `--password` CLI option in the wrapper.

## Source modes

The ranked-room IDs are taken from the Amae-Koromo mode definitions:

| Mortal mode | API family | Default priority |
| --- | --- | --- |
| 3P | `pl3` | Sanma Throne 26 -> Sanma Jade 24 -> Sanma Gold 22 |
| 4P | `pl4` | Throne 16 -> Jade 12 -> Gold 9 |

`--rooms high` is the default and uses only those hanchan ranked rooms. `--rooms all` preserves the same hanchan priority first, then permits East-room fallback:

- 3P East fallback: 25 -> 23 -> 21.
- 4P East fallback: 15 -> 11 -> 8.

The wrapper never drops to a lower-priority room once the requested target can be filled from the rooms already considered.

## First preparation

After the unified RTX validation has passed:

```powershell
git pull
.\RUN_MAJSOUL_FULL.bat prepare <3p_target> <4p_target> authorized <grp_steps> cn
```

For a custom range or a single mode, call the Python wrapper directly:

```powershell
$env:MORTAL_ROGS_MAJSOUL_USERNAME = "<account>"
C:\Users\small\Downloads\Mortal_Unified\.venv\Scripts\python.exe `
  .\scripts\prepare_majsoul_training.py `
  --runtime-root C:\Users\small\Downloads\Mortal_Unified `
  --modes both `
  --start-date 2026-01-01 `
  --end-date 2026-08-30 `
  --rooms high `
  --server jp `
  --api-rps 4 `
  --download-delay-ms 300 `
  --authorized-local-use
```

Omit `--start-date` to scan back to the earliest supported date for each mode. Omit `--end-date` to use yesterday in UTC. The batch launcher intentionally keeps the common path small.

`--api-rps` is capped at 4 by the wrapper. UUID discovery is resumable through the local metadata and room/day scan journal, and raw protobuf downloading is resumable through the pinned downloader's completion journal.

If the account belongs to another supported Mahjong Soul server, choose `cn`, `en`, or `jp`.

## Training and comparison

Once preparation succeeds:

```powershell
.\RUN_MAJSOUL_FULL.bat experiment <3p_target> <4p_target> authorized <grp_steps> cn
```

This prepares/reuses data and GRP state, then hands off to the existing fair ablation runner:

```text
Mortal
ROGS
ROGS + Global
```

For the complete experiment plus production serving soak:

```powershell
.\RUN_MAJSOUL_FULL.bat full <3p_target> <4p_target> authorized <grp_steps> cn
```

The existing `run_local_workstation.ps1` remains the owner of training, comparison, and serving-soak orchestration.

## Baseline checkpoint behavior

A user-supplied or existing mode-compatible `baseline.pth` is preserved and ABI-checked.

If no baseline exists, the preparation path falls back to the checkpoint produced by the validated unified smoke. That checkpoint is only the fixed canonical `train.py` test-play reference; it is not treated as a strong pretrained policy or as the GRP model.

GRP is trained from the prepared real logs and remains mode-specific.

## Files

Local data is kept under the unified runtime:

```text
Mortal_Unified/
  runtime/
    majsoul-cache/
      3p/
        discovery.jsonl
        scanned-days.log
      4p/
        discovery.jsonl
        scanned-days.log
    3p/
      data/majsoul-high-rank/
    4p/
      data/majsoul-high-rank/
```

The cache contains UUID discovery metadata, completed discovery-window journals, raw protobuf files, converter output, and resumable download journals. These files are local runtime artifacts and are not committed to Git.
