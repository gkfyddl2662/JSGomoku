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

For non-interactive local execution, set `MORTAL_ROGS_MAJSOUL_USERNAME` and `MORTAL_ROGS_MAJSOUL_PASSWORD`, call `scripts/prepare_majsoul_training.py` directly, and clear the variables after the run.

## Source modes

The ranked-room IDs are taken from the Amae-Koromo mode definitions:

| Mortal mode | API family | Priority |
| --- | --- | --- |
| 3P | `pl3` | Sanma Throne -> Sanma Jade -> Sanma Gold |
| 4P | `pl4` | Throne -> Jade -> Gold |

Only hanchan ranked-room IDs are selected by the default preparation path. East-only rooms are intentionally excluded from the first training bootstrap.

## First preparation

After the unified RTX validation has passed:

```powershell
git pull
.\RUN_MAJSOUL_FULL.bat prepare <3p_target> <4p_target> authorized <grp_steps> cn
```

For custom date ranges, API RPS, download delay, or a single game mode, call `scripts/prepare_majsoul_training.py` directly. The batch launcher intentionally keeps the common path small.

`ApiRps` is capped at 4 by the wrapper. UUID discovery is resumable through the local cache, and raw protobuf downloading is resumable through the pinned downloader's completion journal.

If the account belongs to another supported Mahjong Soul server, choose `en` or `jp` as the final batch argument.

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
      4p/
    3p/
      data/majsoul-high-rank/
    4p/
      data/majsoul-high-rank/
```

The cache contains UUID discovery metadata, raw protobuf files, converter output, and resumable download journals. These files are local runtime artifacts and are not committed to Git.
