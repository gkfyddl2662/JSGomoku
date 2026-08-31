# Rating-aware Mortal-ROGS for 3P and 4P

## Non-negotiable deployment constraint

Akagi-NG uses two different Mortal runtimes:

- 4P: `libriichi`, 46 actions, standard Mortal v4 checkpoint
- 3P: `libriichi3p`, 44 actions, standard Mortal v4 checkpoint

Therefore one physical checkpoint cannot serve both modes. The training *algorithm* is shared, but final weights are separate:

- `mortal.pth` (4P)
- `mortal3p.pth` (3P)

Both keep only `config`, `mortal`, and `current_dqn` at deployment.

## Why rating-aware reward matters

The same Mahjong result can have different ladder value on different platforms.

Examples:

- Tenhou dan points are placement/table/rank dependent and do not use raw end score for dan-point movement.
- Tenhou Rate is a separate objective using placement plus opponent-average-R correction.
- Mahjong Soul combines raw end score, uma and room/rank-dependent RankPts; the loss for last place becomes strongly rank dependent.
- Riichi City uses rank/room/mode-specific placement tables.
- Amatsuki Japanese ranked points combine raw score, uma and rank-dependent RankPts/last-place penalties.

Training only on `[+6, 0, -6]` or `[+3, +1, -1, -3]` therefore teaches the wrong late-game risk preference for many ladders.

## ABI-safe solution

Rating context is NOT appended to the neural observation. Doing so would change `Brain` input shape and break Akagi-NG compatibility.

Instead:

```text
public Mahjong observation ──────────────> Mortal v4 Brain/DQN
                                                │
terminal rank/score ─> RatingPreset ─> utility ─┘ training loss only
```

Platform, room, current ladder rank and rating are trainer/evaluator metadata only.

## Three training strategies

### universal

At the start of each generated game, sample a rating objective from a configured mixture. The resulting model learns a robust compromise across ladders.

This is useful as a reusable initialization, but the checkpoint cannot magically change its preference at inference because no platform identifier exists in the Mortal ABI.

### specialized

Use one preset for the complete training/fine-tuning run.

Examples:

- `3p / mahjongsoul / throne / saint3 / south`
- `4p / tenhou_dan / houou / 8dan / south`
- `4p / riichi_city_galaxy / 9dan / south`

### curriculum (recommended)

Train universally first, then anneal to a selected target preset.

Default schedule:

```text
0% ------------------- 70% ----------------------- 100%
      universal mix          target probability 0 -> 1
```

This keeps broad Mahjong strength while learning platform-specific late-game risk preference near the end.

## Platform preset engine

`config/rating_presets.toml` is versioned and data-driven. `training/rating.py` and `training/platform_rating.py` implement:

- generic score + uma + placement tables
- decomposed room-dependent + rank-dependent placement values
- official Tenhou dan-point shape for 1dan..10dan
- official Tenhou Rate formula
- normalized utility for stable RL targets

Unknown contexts are errors. The trainer does not silently substitute a guessed rule.

This is important because platform rules can change over time.

## Universal mixtures are mode-specific

`config/rating_presets.toml` defines separate `[universal.3p]` and `[universal.4p]` mixtures. A platform may support both modes but reward them differently.

The self-play league must also be mode-specific:

```text
3P league: 3P latest/champion/history only
4P league: 4P latest/champion/history only
```

Crossing 3P and 4P checkpoints is never allowed.

## Global Reward Predictor integration

The RatingPreset terminal utility becomes the target for the Suphx-style global reward predictor.

For a game state `s_t`:

```text
Phi(s_t) = predicted normalized final rating utility
r_t       = base_hand_reward + gamma * Phi(s_{t+1}) - Phi(s_t)
```

This makes the value model learn the actual ladder objective, not merely raw points or average placement.

## ACH integration

Actor-Critic Hedge (ACH) is a regret-oriented actor-critic method derived from a neural weighted-CFR formulation for two-player zero-sum imperfect-information games.

ROGS borrows two ideas:

1. regress sampled advantage as a regret-like signal
2. generate exploratory self-play policy with Hedge over learned advantage

For 3P and 4P Mahjong this is an optimization heuristic only. The two-player zero-sum Nash-convergence theorem does not transfer to multiplayer Mahjong.

## Deployment and automatic preset selection

Because the model ABI contains no platform flag, runtime specialization must be performed by model selection, not by changing tensors.

Recommended deployment catalog:

```text
models/
  3p/
    universal.pth
    mahjongsoul.pth
    tenhou_dan.pth
    riichi_city_galaxy.pth
  4p/
    universal.pth
    mahjongsoul.pth
    tenhou_dan.pth
    riichi_city_galaxy.pth
```

The control center can select a preset and copy/export the chosen checkpoint under the ordinary Akagi-NG filename. Akagi-NG then loads it as a normal Mortal model with no new network class.

## Evaluation

Every candidate should be evaluated against the exact objective used to train it.

Store at least:

- average rank
- placement distribution
- raw score EV
- normalized rating utility EV
- actual platform rating-point EV
- agari/houjuu/riichi/fuuro rates
- final-round placement conversion matrix

For Universal models, report every preset separately plus their weighted aggregate. This prevents a gain on one ladder from hiding regression on another.
