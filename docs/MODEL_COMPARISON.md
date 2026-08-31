# Mortal-ROGS model comparison

Mortal-ROGS compares 3P and 4P checkpoints with the same duplicate-game principle used by Mortal's strength documentation, while keeping 3P and 4P model ABIs completely separate.

## What is compared

For two checkpoints, `Candidate` and `Baseline`, `scripts/run_model_comparison.py` runs both directions with the same seed range and the same seed key:

1. Candidate as the single challenger against Baseline copies.
2. Baseline as the single challenger against Candidate copies.

For every duplicate seed, the challenger is rotated through every seat:

- 3P: three games per seed (`a`, `b`, `c`).
- 4P: four games per seed (`a`, `b`, `c`, `d`).

The duplicate arena makes the wall, initial hands, dora/ura indicators, and rinshan deterministic for the same `(seed, kyoku, honba)` context. Swapping challenger/champion and keeping the same seed range reduces role/config asymmetry when comparing close checkpoints.

## Metrics

The compact strength report contains the upper section of Mortal's public strength tables:

- games
- placement counts and rates
- tobi count/rate
- average rank
- total and average rank points
- total and average game score delta

Default rank-point vectors are:

- 3P: `[6, 0, -6]`
- 4P: `[90, 45, 0, -135]`, matching Mortal's strength documentation

The native report additionally calls the patched `libriichi.Stat` implementation and records Mortal-style tactical metrics such as:

- win rate
- deal-in rate
- call rate
- riichi rate
- ryukyoku rate
- the complete native `Stat` text table

The paired JSONL is also compatible with the existing platform-rating promotion gate, which evaluates rating utility, average rank, and last-place rate with paired bootstrap confidence intervals.

## Outputs

A comparison run is written below:

`runtime/<mode>/runs/comparison/<comparison-name>/`

Important files:

- `candidate-vs-baseline/` — native duplicate logs with Candidate as challenger
- `baseline-vs-candidate/` — native duplicate logs with Baseline as challenger
- `paired.jsonl` — paired seed/seat records for the promotion gate
- `paired.summary.json` — compact machine-readable strength comparison
- `paired.summary.md` — Mortal-style compact Markdown table
- `native-stat.json` — native `libriichi.Stat` metrics
- `native-stat.txt` — full native `Stat` text tables
- `promotion-gate.json` — created when a rating profile is supplied
- `comparison.json` — manifest tying the run together

## Sample size

`--seed-count 100` is intentionally a quick preview default, not a claim of statistically proven model superiority.

Because every seed produces one game per seat, one direction contains:

- 3P: `3 × seed_count` challenger games
- 4P: `4 × seed_count` challenger games

The bidirectional runner executes both directions, so total simulated games are twice those values.

Mortal's public documentation uses much larger experiments when separating very close model versions; some published comparisons use 1,000,000 challenger games and then repeat the experiment with Challenger and Champion swapped. Mortal-ROGS therefore does not attach a universal 'enough games' threshold to the preview default. Increase the seed count until the paired bootstrap interval and the practical effect size are stable for the intended platform/rating profile.

## Web UI

The Control Center `EXPERIMENTS` panel can start:

- `Mortal` ablation: ROGS off, global reward off
- `ROGS` ablation: ROGS on, global reward off
- `ROGS + Global reward` ablation
- bidirectional checkpoint comparison

All experiment processes use the existing JobManager, so status, logs, and stop controls remain in the normal `JOBS` panel.

## CLI example

```powershell
C:\Users\small\Downloads\Mortal_Unified\.venv\Scripts\python.exe `
  C:\Users\small\Downloads\mortal-rogs\scripts\run_model_comparison.py `
  --runtime-root C:\Users\small\Downloads\Mortal_Unified `
  --mode 4p `
  --candidate ablation\seed-36887\rogs\current.pth `
  --baseline best_mortal.pth `
  --candidate-name ROGS `
  --baseline-name Mortal `
  --seed-start 10000 `
  --seed-count 100 `
  --seed-key 0xD5DFAA4CEF265CD7 `
  --device cuda:0 `
  --profile mahjongsoul
```

For 3P, use `--mode 3p`; the same runner selects the unified `OneVsTwo` duplicate evaluator and the 3P action/observation ABI automatically.
