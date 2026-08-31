# Mortal Population Self-play Bootstrap

This path is for cases where a few usable Mortal v4 checkpoints are available but large human-log downloads are unreliable or unavailable.

The goal is not to imitate one fixed checkpoint forever. The checkpoints are used as the initial Champion/opponent population, Mortal/libriichi generates real MJAI game logs locally, and the existing GRP + Mortal/ROGS training pipeline learns from those trajectories.

## Intended starting point

A practical initial setup can be as small as:

- 4P: one known-good checkpoint plus one uncertain checkpoint.
- 3P: one uncertain checkpoint.

The known-good checkpoint should be supplied first. Every checkpoint is still validated against the current unified Mortal v4 ABI before it becomes active.

## Validation gates

`prepare_selfplay_population.py` performs, per checkpoint:

1. SHA-256 identification/deduplication.
2. Mortal v4 mode-specific load and inference through `check_mortal_api_checkpoint.py`.
3. By default, a real 3P `one_vs_two.py` or 4P `one_vs_three.py` gameplay smoke through `run_model_comparison.py` with one duplicate context.
4. Only checkpoints that pass are copied under `runtime/<mode>/models/population/`.
5. Wrong-mode, incompatible, corrupt, or gameplay-failing checkpoints are recorded as rejected and are not copied into the active pool.

The population manifest is:

```text
Mortal_Unified/runtime/3p/models/population/population.json
Mortal_Unified/runtime/4p/models/population/population.json
```

For a single valid 3P checkpoint the initial schedule uses mirror self-play. Learner/checkpoint snapshots can later be re-imported to increase opponent diversity.

## Champion installation

After validation, `install_population_champion.py` can install the selected Champion into all three existing Mortal slots:

```text
current.pth
best_mortal.pth
baseline.pth
```

If a different file already occupies one of those slots, it is preserved first under:

```text
runtime/<mode>/models/bootstrap-backup/<timestamp>/
```

A hardlink is used for the backup when possible; otherwise the file is copied. The installed file is hashed after replacement.

This means:

- `current.pth` starts/continues learner training from the validated Champion.
- `best_mortal.pth` is the initial evaluation/deployment Champion.
- `baseline.pth` provides the fixed Mortal/BC anchor used by the existing config.

## One-click commands

From the repository directory:

```powershell
# 3P: one available checkpoint
.\RUN_SELFPLAY_POPULATION.bat prepare 3p "D:\models\sanma.pth"

# 4P: known-good checkpoint first, uncertain checkpoint second
.\RUN_SELFPLAY_POPULATION.bat prepare 4p "D:\models\verified-4p.pth" "D:\models\other-4p.pth"
```

The first checkpoint is marked trusted/preferred Champion, but it must still pass the current runtime checks.

If an uncertain checkpoint fails, the command can still succeed as long as at least one checkpoint passes. The failed model remains outside the active pool and its reason is written to the population manifest.

## Generate local training logs

Generate at least 1,000 real Mortal/libriichi game logs:

```powershell
.\RUN_SELFPLAY_POPULATION.bat generate 3p 1000
.\RUN_SELFPLAY_POPULATION.bat generate 4p 1000
```

The runner uses the existing evaluator rather than a new game engine:

- 3P: challenger 1 seat vs Champion 2 seats with duplicate seat rotation.
- 4P: challenger 1 seat vs Champion 3 seats with duplicate seat rotation.
- With two or more accepted models, both directions are scheduled before mirror Champion games.
- With one accepted model, mirror self-play is used until the pool expands.

Generated logs are placed under:

```text
Mortal_Unified/runtime/<mode>/data/selfplay-population/train/
Mortal_Unified/runtime/<mode>/data/selfplay-population/val/
```

They are checked with both the real Mortal `GameplayLoader` and the GRP loader before success is reported.

## Activate generated data for training

Add `activate` to update only that mode's Mortal/GRP dataset globs:

```powershell
.\RUN_SELFPLAY_POPULATION.bat generate 3p 1000 activate
.\RUN_SELFPLAY_POPULATION.bat generate 4p 1000 activate
```

After activation, the existing Control Center training actions can be reused:

```text
GRP training
Offline Mortal / ROGS training
Evaluation
Bidirectional duplicate comparison
Promotion gate
```

No new checkpoint format is introduced. Deployment remains ordinary Mortal v4 `Brain + current_dqn` compatible with the existing Akagi-facing server.

## Human logs

Tenhou/Mahjong Soul logs are optional in this path. A small 3P/4P Tenhou set can still be retained for independent validation/calibration, but self-play generation no longer waits for a large external archive.

## Next population step

After a learner checkpoint is produced:

1. Keep the current Champion frozen.
2. Add the learner/snapshot as another population candidate.
3. Generate cross-play data with the expanded pool.
4. Compare Challenger vs Champion with the existing bidirectional duplicate evaluator.
5. Replace the Champion only through the normal promotion gate.

This avoids turning self-play into pure fixed-policy self-imitation while still using every compatible checkpoint available at bootstrap.
