# Mortal-ROGS v4: Regret / Oracle / Global Reward / Search Distillation

This document defines an experimental training paradigm for **3-player Mortal** while preserving the deployed Mortal checkpoint ABI expected by **Akagi-NG**.

## Non-negotiable deployment contract

The final deployable checkpoint remains a normal Mortal model:

- `state['config']['control']['version'] == 4`
- `state['mortal']` is the ordinary Mortal `Brain` state dict
- `state['current_dqn']` is the ordinary Mortal v4 `DQN` state dict
- 3-player action space is exactly `44`
- no oracle/search/regret-specific parameter is required during inference
- the checkpoint must pass `scripts/check_akagi_compat.py` against the actual Akagi-NG installation and its `libriichi3p`

Akagi-NG currently reconstructs the Mortal network from the checkpoint config, supports local Mortal model versions 1-4, and checks a 44-action output for 3-player play. Therefore a sanma training fork using a custom model version such as v5 must **not** be treated as deployment-compatible merely because its PyTorch layers look similar.

## Source ideas and limits

### Suphx

Paper: *Suphx: Mastering Mahjong with Deep Reinforcement Learning* (Li et al., 2020)

- https://arxiv.org/abs/2003.13590
- https://www.microsoft.com/en-us/research/publication/suphx-mastering-mahjong-with-deep-reinforcement-learning/

Useful ideas:

1. supervised warm start from strong human games
2. self-play reinforcement learning
3. global reward prediction to assign game-level placement incentives to individual rounds
4. oracle guiding using privileged hidden information during training
5. parametric Monte-Carlo policy adaptation (pMCPA)

### LuckyJ / Tencent line of work

Tencent publicly states that LuckyJ learned through self-play, and public/secondary descriptions associate the Tencent Mahjong line with neural CFR/regret-style policy optimization. The fully detailed four-player Riichi LuckyJ training recipe is **not publicly disclosed as a reproducible paper**. We therefore do not claim to reproduce LuckyJ itself.

The reproducible algorithmic reference used here is the Tencent AI Lab ICLR 2022 paper:

*Actor-Critic Policy Optimization in a Large-Scale Imperfect-Information Game* (Fu et al., 2022)

- https://openreview.net/forum?id=DTXZqTNV5nW
- https://mlanthology.org/iclr/2022/fu2022iclr-actorcritic/

It introduces Actor-Critic Hedge (ACH), a neural weighted-CFR-inspired method that trains policy preference from sampled cumulative advantage/regret.

Important limitation: ACH's Nash-convergence motivation is for **two-player zero-sum** games. Three-player sanma is not that setting. ROGS therefore uses regret learning as a practical self-play optimization signal, **not as a claim of Nash convergence**.

Tencent LuckyJ public self-play statement:

- https://www.tencent.com/en-us/articles/2201746.html

## Core idea: teacher complexity, student simplicity

Do **not** add search results, opponent hidden tiles, wall tiles, recurrent state, or extra heads to the deployed Mortal input/output.

Instead:

```text
                 TRAINING ONLY

  expert logs -----------+
                         |
  GRP potential ---------+----> Mortal v4 Student ----> mortal3p.pth
                         |        Brain B40C192             |
  Oracle teacher --------+        DQN 1+44                  |
                         |                                  v
  Search teacher --------+                         Akagi-NG unchanged
                         |
  Regret self-play ------+
```

The expensive information is used only to generate better targets. The static Mortal student learns to amortize those targets from the normal public observation.

## Why Mortal v4 DQN fits regret training unusually well

Mortal v4 already has one final linear layer producing:

```text
[V(s), A(s,a_1), ..., A(s,a_44)]
```

and constructs dueling Q values by centering the action terms.

ROGS reuses those existing action outputs as a neural preference/regret representation during self-play. **No new parameter is added.** At deployment, Akagi-NG still calls the ordinary DQN forward method and chooses the largest Q value. Since adding the same V value to every legal action does not change `argmax`, regret-guided action preference remains directly deployable.

`training/rogs.py` exposes this parameter-free decomposition.

## Training stages

### Stage 0 - ABI lock and baseline

Before training:

1. copy the currently usable Akagi-NG 3P model as the immutable baseline
2. run `check_akagi_compat.py`
3. record `libriichi3p.consts.obs_shape(4)` and `ACTION_SPACE`
4. use the **same libriichi3p observation ABI** for training and evaluation

Never assume that another sanma fork's `version=4` means the same feature layout.

### Stage 1 - expert warm start

Start from the strongest available compatible Mortal model or expert data.

Use a mixture of:

- behavior cloning anchor
- existing Mortal Monte-Carlo/CQL objective
- next-rank / auxiliary losses when useful

The BC/CQL terms should decay rather than disappear immediately. Their purpose later is to keep regret self-play from drifting into pathological self-play conventions.

### Stage 2 - Global Reward Predictor (Suphx)

Train a separate GRP on sequences of round-level information. For sanma, the prediction target should be configurable by target platform.

Recommended utility:

```text
U = rank_points[final_rank]
    + score_delta_weight * tanh(final_score_delta / score_scale)
```

Use potential-based shaping:

```text
r'_k = r_k + gamma * Phi(x_k) - Phi(x_{k-1})
```

The GRP is training-only and does not enter the deployed checkpoint.

### Stage 3 - privileged Oracle teacher (Suphx-inspired)

During self-play the simulator knows opponent hands and wall tiles. Train a separate oracle teacher on these privileged features.

Do **not** enlarge the student input channels.

Instead distil teacher action preferences into the ordinary Mortal student:

```text
L_oracle = KL(
    softmax(Q_oracle / T),
    softmax(Q_student / T)
)
```

Schedule the oracle loss weight downward as training progresses. This implements the spirit of Suphx oracle guiding while keeping the deployed network identical to Mortal.

### Stage 4 - Regret-guided league self-play (ACH/LuckyJ-inspired)

For each student decision:

1. obtain `V(s)` and centered `A(s,a)` from the unchanged Mortal v4 DQN
2. derive a stochastic Hedge policy from action preferences
3. generate self-play trajectories against a mixture of latest/champion/historical opponents
4. compute game/round returns using GRP shaping
5. estimate sampled advantage `R - V(s)`
6. train the selected action's centered advantage toward the regret-like sampled-advantage target
7. simultaneously keep a value/Q anchor objective

Suggested combined loss:

```text
L = w_value   * L_value
  + w_regret  * L_regret
  + w_oracle  * L_oracle
  + w_search  * L_search
  + w_bc      * L_BC
  + w_cql     * L_CQL
  - w_entropy * H(policy)
```

The value/Q anchor is important because Akagi-NG exposes Q-like values in recommendation metadata. Pure regret values can have poor calibration even when their action ranking is strong.

### Stage 5 - Search as Teacher, never Search as Feature

Some secondary descriptions of LuckyJ mention game-tree/search-derived information. Feeding search features into Mortal directly would break the observation ABI.

ROGS instead performs sampled hidden-state rollouts only on a subset of important states:

- riichi decisions
- push/fold inflection points
- late-turn defense
- final-round placement decisions
- high-value open-hand decisions

For each candidate action, sample hidden worlds consistent with public information, perform rollouts, and estimate a teacher action value. Distil that distribution into the standard student Q output.

This is intentionally expensive but sparse.

### Stage 6 - amortized pMCPA

Suphx pMCPA adapts the policy at run time for a fixed initial hand. Akagi-NG's ordinary Mortal inference path does not perform temporary gradient updates, so direct pMCPA would violate the desired deployment model.

ROGS moves the idea offline:

1. fix a sampled initial hand
2. clone the student temporarily
3. simulate many compatible hidden worlds
4. perform a few inner-loop updates on the clone
5. use the adapted clone as a teacher
6. distil its decisions back into the global static Mortal student
7. discard the clone

This can be viewed as **amortized policy adaptation**: expensive hand-specific adaptation happens during training; inference remains one Mortal forward pass.

## League instead of latest-only self-play

Three-player self-play is vulnerable to cycling and non-transitive policies. Use a small population:

- latest student: 45%
- current champion: 30%
- historical snapshots: 25%

Rotate all three seats. Periodically add snapshots, but prune dominated/redundant models.

This does not provide a formal equilibrium guarantee; it is a practical robustness mechanism for multiplayer general-sum training.

## Promotion gate

Do not promote a model based on training loss.

Minimum gate:

- 12,000+ 1v2 games
- exact seat rotation
- challenger against two champion copies
- cross-play against historical population
- bootstrap confidence intervals
- average rank improvement
- 1st/2nd/3rd rates
- target-room rank points
- deal-in rate, win rate, riichi rate, call rate
- final-round placement conversion

A candidate should also pass the exact Akagi-NG compatibility probe before it can become champion.

## Export rule

Training checkpoints may contain:

```text
mortal
current_dqn
optimizer
scheduler
oracle_teacher
search_teacher
regret_state
grp
league_metadata
...
```

Deployment export should retain only the normal Mortal fields required by the consumer, especially:

```text
config
mortal
current_dqn
```

Training-only networks must never be merged into `mortal` or `current_dqn` state dicts.

## First experimental matrix

Run ablations before scaling self-play:

| Experiment | GRP | Oracle | Regret | Search | Amortized pMCPA |
|---|---:|---:|---:|---:|---:|
| Mortal baseline | yes | no | no | no | no |
| R | yes | no | yes | no | no |
| RO | yes | yes | yes | no | no |
| ROGS | yes | yes | yes | yes | no |
| ROGS+A | yes | yes | yes | yes | yes |

Promote components only when they improve held-out cross-play, not merely self-play reward.
