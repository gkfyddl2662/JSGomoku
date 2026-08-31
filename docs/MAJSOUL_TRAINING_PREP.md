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

The external converter/downloader remains pinned to:

```text
NikkeTryHard/tenhou-to-mjai
69fb75a51c7efef3212be603227b2a58a9717237
```

The pin itself is not forked or moved. For current EN authentication, Mortal-ROGS applies the small managed compatibility patch `patches/tenhou-to-mjai-yostar-en.patch` to that exact runtime checkout before building it. The build marker includes the patch digest, so changing the patch forces a rebuild while repeated runs reuse the binary.

Its Majsoul converter emits `nukidora` for 3P north-tile extraction and supports both three- and four-player MJAI output.

## Local-data policy

Use this tool only for records you are permitted to access. Downloaded Mahjong Soul records stay local and must not be redistributed.

The repository contains tooling only. It does not contain, publish, mirror, or describe a pre-built Mahjong Soul game-log dataset.

The generated local manifest records source/provenance and preparation configuration but does not store account passwords, Yostar redirect tokens, Mahjong Soul access tokens, or account UIDs.

## Authentication

### EN / Korean web client

The current EN/KR web client no longer follows the native email/password path used by the pinned downloader. A live socket capture confirmed this sequence:

```text
.lq.Lobby.oauth2Auth   type=23, Yostar redirect token + UID
        ↓
Mahjong Soul access token
        ↓
.lq.Lobby.oauth2Check
        ↓
.lq.Lobby.oauth2Login
```

The managed patch connects this flow only for `--server en`. The captured account-specific values are not stored in this repository.

Run:

```powershell
.\RUN_MAJSOUL_FULL.bat prepare <3p_target> <4p_target> authorized <grp_steps> en
```

Interactive execution asks for:

```text
Yostar UID
Yostar redirect token
```

For non-interactive local execution, use process-local environment variables and clear them after the run:

```powershell
$env:MORTAL_ROGS_MAJSOUL_YOSTAR_UID = "<uid>"
$env:MORTAL_ROGS_MAJSOUL_YOSTAR_TOKEN = "<fresh-yostar-redirect-token>"

C:\Users\small\Downloads\Mortal_Unified\.venv\Scripts\python.exe `
  .\scripts\prepare_majsoul_training_yostar.py `
  --runtime-root C:\Users\small\Downloads\Mortal_Unified `
  --modes both `
  --server en `
  --authorized-local-use

Remove-Item Env:MORTAL_ROGS_MAJSOUL_YOSTAR_UID -ErrorAction SilentlyContinue
Remove-Item Env:MORTAL_ROGS_MAJSOUL_YOSTAR_TOKEN -ErrorAction SilentlyContinue
```

There is intentionally no CLI option for a password or Yostar token.

The pinned child CLI still exposes a field named `--password`; the compatibility layer reuses that internal argument slot to carry the Yostar redirect token into the patched child process. Mortal-ROGS always redacts it from its own command logging, but the token can be transiently visible to local process-inspection tools while the child process is running.

Because an authentication token pasted into a chat or log should be treated as exposed, obtain a fresh Yostar redirect token for the real local validation rather than reusing a previously shared value.

### CN and JP

`cn` keeps the existing native account/password path and the wrapper still supports:

```text
MORTAL_ROGS_MAJSOUL_USERNAME
MORTAL_ROGS_MAJSOUL_PASSWORD
```

The `jp` selector is retained for compatibility, but this change does not claim that its authentication path has been live-validated. Do not generalize the EN/KR `type=23` result to JP until a real JP capture/test confirms it.

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

After the unified RTX validation has passed, the first EN validation should stay small:

```powershell
git pull
.\RUN_MAJSOUL_FULL.bat prepare 5000 5000 authorized 10000 en
```

For a custom range or a single mode:

```powershell
C:\Users\small\Downloads\Mortal_Unified\.venv\Scripts\python.exe `
  .\scripts\prepare_majsoul_training_yostar.py `
  --runtime-root C:\Users\small\Downloads\Mortal_Unified `
  --modes both `
  --start-date 2026-01-01 `
  --end-date 2026-08-30 `
  --rooms high `
  --server en `
  --api-rps 4 `
  --download-delay-ms 300 `
  --authorized-local-use
```

Omit `--start-date` to scan back to the earliest supported date for each mode. Omit `--end-date` to use yesterday in UTC. The batch launcher intentionally keeps the common path small.

`--api-rps` is capped at 4 by the wrapper. UUID discovery is resumable through the local metadata and room/day scan journal, and raw protobuf downloading is resumable through the pinned downloader's completion journal.

## Training and comparison

Once preparation succeeds:

```powershell
.\RUN_MAJSOUL_FULL.bat experiment <3p_target> <4p_target> authorized <grp_steps> en
```

This prepares/reuses data and GRP state, then hands off to the existing fair ablation runner:

```text
Mortal
ROGS
ROGS + Global
```

For the complete experiment plus production serving soak:

```powershell
.\RUN_MAJSOUL_FULL.bat full <3p_target> <4p_target> authorized <grp_steps> en
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
