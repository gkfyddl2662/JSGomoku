# Evaluation backends: MJX first, no fake sanma support

## Decision

Mortal-ROGS uses different simulation backends behind one evaluation interface:

| Mode | Primary | Reference / cross-check | Reason |
|---|---|---|---|
| 4P | MJX | libriichi, optional gimite/mjai | MJX is the high-throughput evaluator and supports batched agents. |
| 3P | libriichi3p | same engine with independent seeds/checkpoints | Upstream MJX and original gimite/mjai are four-player oriented. |

The neural-network ABI remains Akagi-NG Mortal v4. The simulator is an evaluation/training infrastructure choice and does not change `mortal`, `current_dqn`, observation planes, or action dimensions exported to Akagi-NG.

## Why MJX for 4P

Upstream MJX describes itself as a C++/Python riichi Mahjong simulator and claims more than 100x the speed of the original Mjai. It also provides gRPC/distributed execution, a Gym-like API, Tenhou validation, and batched `Agent.act_batch` inference. The last point is particularly useful for Mortal: states from multiple simultaneous games can be queued into one GPU batch instead of doing one neural-network call per game step.

MJX `EnvRunner` can save one JSON result per game containing the game seed, final scores (`tens`) and rankings. Our promotion gate can therefore use paired seeds, rotate seats, and feed the same terminal result into the platform RatingUtility layer.

## Why MJX is not used for 3P

The current upstream implementation constructs four default player IDs, contains four-place reward maps/statistics, and has no sanma implementation in the public source. We intentionally reject `backend=mjx` for 3P rather than silently running a different game.

The original `gimite/mjai` is not a sanma fallback either. Its game loop and initial hand/wall setup contain four-seat assumptions. Therefore Mortal-ROGS keeps the Akagi-compatible `libriichi3p` engine for sanma.

## Windows runtime

Upstream MJX does not support native Windows. For this project the 4P evaluator runs in WSL2 or a Linux container. The main Web UI can remain on Windows and launch/monitor the WSL evaluation worker.

Because the current MJX master README warns that master may not build, the initial integration is pinned to public release `v0.1.0`. Upgrade the pinned ref only after bridge and rule-parity tests pass.

Use:

```powershell
.\scripts\setup_mjx_eval_wsl.ps1
```

## Mortal bridge strategy

There are two bridge stages.

### Stage A: reference bridge

Use `mjx-project/mjx_mjai_translater` as a behavioral reference. It proves that an MJX observation/action stream can be translated to an Mjai-speaking AI. Small cross-check batches are used to validate our event/action conversion.

### Stage B: native bridge

The production evaluator will avoid Ruby and translate MJX observations/events directly to the Mortal/libriichi interface. MJX observations expose the current hand, legal actions/action mask, event history, draws, dora, scores, honba, kyotaku, dealer and round, so the required information is available.

The native agent will implement batched inference:

```text
MJX games (many CPU threads)
        |
        v
observation queue
        |
        v
MJX->Mortal state adapter
        |
        v
Mortal Brain + DQN GPU batch
        |
        v
Mortal action -> MJX Action
        |
        v
MJX games
```

## Evaluation protocol

High-volume candidate gates use:

1. fixed seed groups;
2. full seat rotation;
3. candidate/champion/historical opponents;
4. at least 12,000 games for a promotion gate by default;
5. average rank and place rates;
6. raw-score EV;
7. platform-specific RatingUtility EV;
8. bootstrap confidence intervals;
9. agari, houjuu, riichi and fuuro rates where the backend log exposes them.

For 4P, a small subset is cross-checked against libriichi before trusting a new MJX bridge/ref. For 3P, the high-volume engine is libriichi3p itself.

## Suphx connection

MJX also contains an archived/experimental `workspace/suphx-reward-shaping` implementation that predicts later game reward from earlier rounds. We do not depend on those model weights or architecture, but it is useful as an independent reference when validating the ROGS global-reward/potential-shaping implementation.
