# Mortal-ROGS ABI and Wire Contracts

This document separates three contracts that were previously described as if they were one.

## 1. AkagiOT wire ABI — hard external compatibility boundary

Untouched Akagi-NG owns MJAI state tracking and its native observation encoder. Mortal-ROGS receives only `obs` and `masks` over HTTP and returns `actions`, `q_out`, `masks`, and `is_greedy`.

| Mode | Endpoint | Akagi encoder | Wire observation | Actions |
|---|---|---|---:|---:|
| 3P | `/react_batch_3p` | pinned `libriichi3p`, v4 | `(775, 34)` | 44 |
| 4P | `/react_batch` | pinned `libriichi`, v4 | `(1012, 34)` | 46 |

The 3P wire shape is intentionally different from Mortal-ROGS's native research/training observation.

## 2. Native Mortal-ROGS training ABI — internal research contract

| Mode | Native observation | Oracle observation | Actions | GRP input |
|---|---:|---:|---:|---:|
| 3P | `(1010, 34)` | `(170, 34)` | 44 | 6 |
| 4P | `(1012, 34)` | `(217, 34)` | 46 | 7 |

The 3P `(1010,34)` representation is a unified Mortal-ROGS training/runtime representation. It must not be confused with Akagi-NG's historical `(775,34)` sanma encoder. The two feature layouts are semantic encodings, not padding-compatible tensors.

## 3. Model/checkpoint ABI — server implementation choice

AkagiOT does **not** load a Mortal checkpoint and does not inspect `config`, `mortal`, `current_dqn`, Mortal `Brain`, or Mortal `DQN` state dictionaries.

Therefore the HTTP integration does not require the server's model to be a Mortal v4 checkpoint. Mortal v4 remains an important compatibility backend because it provides:

- existing strong 3P/4P checkpoints,
- Champion/baseline population members,
- historical comparison,
- a known training/evaluation implementation,
- checkpoint import/export compatibility for users who need standard Mortal files.

A future or experimental Mortal-ROGS-native backend may use a different internal architecture/checkpoint format as long as the selected deployment backend consumes the exact Akagi wire observation and produces the exact action-space response.

## Current implementation status

### Mortal v4 compatibility backend

`serving/inference.py` currently implements a Mortal checkpoint loader and therefore still enforces Mortal-specific state and model construction. That enforcement is a property of the **current backend**, not the AkagiOT protocol.

### 3P deployment gap

The current native 3P learner uses `(1010,34)` while untouched Akagi-NG produces `(775,34)` for online 3P inference. A native 1010 checkpoint cannot be connected to the 775 wire by zero-padding or channel reshaping because the feature semantics differ.

Until a deployment strategy is selected and validated, the following are distinct:

- `native-1010`: research/training/evaluation learner ABI;
- `akagi-wire-775`: untouched Akagi-NG online inference ABI;
- `legacy-775`: existing Akagi/Mortal-Sanma compatible checkpoints already usable as population teachers/opponents.

The current synthetic AkagiOT client smoke constructs tensors directly and therefore must not be interpreted as proof that the full `libriichi3p.mjai.Bot -> AkagiOT -> server` 3P path accepts the native 1010 learner.

## Safe deployment options for 3P

1. Train/fine-tune a deployment model whose input is the exact 775-channel Akagi wire representation.
2. Keep the richer 1010 model as a research/teacher model and distill into a 775 deployment student.
3. Change the external protocol to send a richer/raw state and re-encode server-side. This would require changing Akagi-NG and is not the current vanilla-client goal.

Option 2 preserves the current native research representation while keeping untouched Akagi-NG compatibility and is the preferred hypothesis to validate first; it is not yet claimed as implemented.

## Design rule

Do not use the phrase `Mortal v4 ABI` without naming which boundary is meant.

Use one of:

- **AkagiOT wire ABI** — external request/response contract;
- **native training ABI** — Mortal-ROGS data/model input contract;
- **Mortal v4 compatibility checkpoint ABI** — optional existing-model backend.

Changing one boundary does not automatically require changing the others.
