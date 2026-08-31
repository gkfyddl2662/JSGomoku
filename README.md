<div align="center">

# Mortal-ROGS

### 3P / 4P Riichi Mahjong Research · Training · Evaluation · Serving

**Mortal 계열의 강한 기존 자산을 유지하면서, 3인마작(Sanma)과 4인마작(Yonma)의 데이터 생성·ROGS 학습·population self-play·duplicate 평가·rating-aware promotion·AkagiOT serving을 하나의 Windows 중심 플랫폼으로 통합하는 프로젝트**

[![Research CI](https://github.com/gkfyddl2662/JSGomoku/actions/workflows/research-ci.yml/badge.svg?branch=research%2Fmortal-rogs-v4-impl)](https://github.com/gkfyddl2662/JSGomoku/actions/workflows/research-ci.yml)
[![Unified Runtime CI](https://github.com/gkfyddl2662/JSGomoku/actions/workflows/unified-runtime-ci.yml/badge.svg?branch=research%2Fmortal-rogs-v4-impl)](https://github.com/gkfyddl2662/JSGomoku/actions/workflows/unified-runtime-ci.yml)
[![Gameplay Contract](https://github.com/gkfyddl2662/JSGomoku/actions/workflows/unified-gameplay-contract-ci.yml/badge.svg?branch=research%2Fmortal-rogs-v4-impl)](https://github.com/gkfyddl2662/JSGomoku/actions/workflows/unified-gameplay-contract-ci.yml)
[![Akagi API](https://github.com/gkfyddl2662/JSGomoku/actions/workflows/akagi-api-contract-ci.yml/badge.svg?branch=research%2Fmortal-rogs-v4-impl)](https://github.com/gkfyddl2662/JSGomoku/actions/workflows/akagi-api-contract-ci.yml)
[![Akagi 3P Compatibility](https://github.com/gkfyddl2662/JSGomoku/actions/workflows/akagi-3p-compat-ci.yml/badge.svg?branch=research%2Fmortal-rogs-v4-impl)](https://github.com/gkfyddl2662/JSGomoku/actions/workflows/akagi-3p-compat-ci.yml)
[![Windows Script CI](https://github.com/gkfyddl2662/JSGomoku/actions/workflows/windows-script-ci.yml/badge.svg?branch=research%2Fmortal-rogs-v4-impl)](https://github.com/gkfyddl2662/JSGomoku/actions/workflows/windows-script-ci.yml)

**Python 3.12 · PyTorch 2.11 / CUDA 12.8 · BF16 · torch.compile · RTX 5080 target · Mortal v4 compatibility backend**

</div>

> [!IMPORTANT]
> 이 저장소는 현재 **연구/개발 브랜치**입니다. 3P와 4P는 하나의 managed runtime을 공유하지만 **config / data / GRP / checkpoint / population / run / promotion state는 mode별로 분리**합니다.

> [!IMPORTANT]
> **AkagiOT wire ABI, Mortal-ROGS native training ABI, Mortal v4 checkpoint ABI는 서로 다른 계약입니다.** Akagi-NG가 HTTP API를 사용할 때 Akagi-NG는 Mortal-ROGS의 `.pth`를 직접 로드하지 않습니다. 자세한 기준은 [`docs/ABI_AND_WIRE_CONTRACTS.md`](docs/ABI_AND_WIRE_CONTRACTS.md)를 참고하십시오.

> [!NOTE]
> Branch: `research/mortal-rogs-v4-impl`  
> Canonical Equim Mortal compatibility pin: `0cff2b52982be5b1163aa9a62fb01f03ce91e0d2`  
> Akagi-NG compatibility pin: `11c0ffc0d70bf8142585b92405b4412976c9e205`

---

## Contents

- [Overview](#overview)
- [Status](#status)
- [Architecture](#architecture)
- [ABI / wire contracts](#abi--wire-contracts)
- [Mortal-ROGS training](#mortal-rogs-training)
- [Training data](#training-data)
- [Population self-play](#population-self-play)
- [Evaluation & promotion](#evaluation--promotion)
- [Rating-aware objectives](#rating-aware-objectives)
- [Akagi-NG API serving](#akagi-ng-api-serving)
- [Control Center](#control-center)
- [Quick start](#quick-start)
- [Local experiments](#local-experiments)
- [Validation](#validation)
- [Roadmap](#roadmap)
- [Repository layout](#repository-layout)
- [Documentation](#documentation)
- [Research boundaries](#research-boundaries)
- [Legacy migration](#legacy-migration)
- [Troubleshooting](#troubleshooting)

---

# Overview

Mortal-ROGS의 목적은 “Mortal 파일 형식을 무조건 유지하는 것”이 아니라 **강한 Mortal 생태계를 호환성 자산으로 활용하면서 더 좋은 3P/4P 학습·평가·배포 구조를 실험하는 것**입니다.

```text
                                Mortal-ROGS
                                     │
          ┌──────────────────────────┼───────────────────────────┐
          │                          │                           │
    Data / Training             Evaluation                   Serving
          │                          │                           │
    ┌─────┴─────┐          ┌────────┴────────┐          ┌───────┴────────┐
    │           │          │                 │          │                │
 3P Sanma    4P Yonma  duplicate/Stat   rating gate   AkagiOT 3P     AkagiOT 4P
    │           │          │                 │          │                │
    └──────┬────┘          └────────┬────────┘          └────────┬───────┘
           │                        │                            │
           └──────────────── Mortal_Unified ─────────────────────┘
                                     │
                   one source / one .venv / one PyO3 stack
                                     │
                       ┌─────────────┴─────────────┐
                       │                           │
                 runtime/3p                  runtime/4p
              data / models / runs        data / models / runs
```

## Design principles

| Principle | Meaning |
|---|---|
| **3P / 4P always supported** | 특정 mode만 남기는 구조로 단순화하지 않습니다. |
| **Mortal v4 stays compatible** | 기존 Mortal v4 checkpoint를 baseline/teacher/Champion/backend로 계속 지원합니다. |
| **Model ABI ≠ Akagi wire ABI** | AkagiOT가 요구하는 것은 HTTP 입력/출력 계약이지 `config/mortal/current_dqn` key가 아닙니다. |
| **No fake 775↔1010 conversion** | 3P 775와 1010 feature는 semantic layout이 다르므로 padding/reshape로 변환하지 않습니다. |
| **Gameplay-level validation** | tensor forward만이 아니라 arena → MJAI → loader → train → checkpoint → evaluator를 확인합니다. |
| **Promotion is statistical** | training loss가 아니라 duplicate + rating gate로 승격 판단합니다. |
| **Correctness before throughput** | MJX 등 고속 backend는 native parity가 증명된 뒤 promotion 경로에 올립니다. |
| **Research claims stay scoped** | LuckyJ/ACH-inspired, Suphx-inspired라고 표현하며 미구현 기능을 완료로 주장하지 않습니다. |

---

# Status

상태 표기:

- ✅ **Implemented / validated** — 구현되어 CI 또는 실제 smoke로 검증됨
- 🧪 **Implemented / measuring** — 구현은 있으나 장시간·대량·실성능 검증 필요
- 🚧 **In progress** — 현재 연결/정합성 작업 중
- 🗺️ **Planned / research** — 설계/가설 단계

## Feature matrix

| Area | 3P | 4P | Notes |
|---|---:|---:|---|
| Unified managed runtime | ✅ | ✅ | one Mortal source / `.venv` / PyO3 stack |
| Mode-isolated config/data/models/runs | ✅ | ✅ | 서로 checkpoint tensor 공유 안 함 |
| Native training observation | ✅ | ✅ | 1010ch / 1012ch |
| Native Oracle observation | ✅ | ✅ | **170ch / 217ch** |
| Native gameplay evaluator | ✅ | ✅ | `OneVsTwo` / `OneVsThree` |
| MJAI → GameplayLoader roundtrip | ✅ | ✅ | actual generated logs |
| Mode-specific GRP | ✅ | ✅ | input 6 / 7 |
| Mortal compatibility checkpoint | ✅ | ✅ | v4 `Brain + current_dqn` backend |
| ROGS composite objective | ✅ | ✅ | value/regret/BC/CQL/entropy |
| Global reward | 🧪 | 🧪 | implemented, **default OFF** |
| ROGS component/weight telemetry | ✅ | ✅ | raw/weighted/coeff/diagnostics |
| Oracle/Search loss interfaces | 🧪 | 🧪 | interface exists, canonical teacher tensors **not connected** |
| Hedge helper | 🧪 | 🧪 | helper/config exists, canonical behavior policy **not connected** |
| Population checkpoint validation | ✅ | ✅ | actual evaluator smoke |
| Population self-play generator | ✅ | ✅ | resumable CLI/BAT |
| Akagi legacy 775 teacher bridge | ✅ | — | 3P population/eval |
| Duplicate seat rotation | ✅ | ✅ | 3 / 4 seats per seed |
| Seed-cluster bootstrap | ✅ | ✅ | same-seed rotations resampled together |
| Native `libriichi.Stat` | ✅ | ✅ | tactical statistics |
| Rating utility/router | ✅ | ✅ | universal/specialized/curriculum foundation |
| Native promotion backend | ✅ | ✅ | libriichi3p / libriichi |
| MJX high-throughput evaluator | 🧪 | 🧪 | explicit experimental parity/throughput path |
| AkagiOT HTTP protocol | ✅ | ✅ | gzip + Authorization + expected response fields |
| Real untouched Akagi 3P wire shape | ✅ | — | pinned Bot probe: 775×34 / 44 |
| Dynamic batching / LKG / hot reload | ✅ | ✅ | shared GPU coordination |
| Benchmark / soak / profile / rollback | ✅ | ✅ | framework implemented; real 30m RTX gate 🧪 |
| Control Center core workflows | ✅ | ✅ | train/eval/serving/experiments |
| Population self-play Web UI | 🚧 | 🚧 | current canonical entry: BAT/CLI |
| Human-log + self-play automatic mixture | 🗺️ | 🗺️ | current activate switches dataset root |
| Non-Mortal internal model backend | 🗺️ | 🗺️ | protocol permits it; current server loader is still Mortal-specific |
| 3P 1010→775 deployment distillation | 🗺️ | — | preferred hypothesis, not implemented |
| Full Oracle/Search/pMCP | 🗺️ | 🗺️ | measurement-gated future work |

## Confirmed local validation

실제 Windows target workstation에서 확인된 범위:

- ✅ RTX 5080, CUDA, BF16, `torch.compile` unified runtime
- ✅ 3P/4P gameplay, MJAI reload, loader, mini-training, strict checkpoint reload, evaluator
- ✅ 4P existing Mortal v4 PTH population validation / Champion installation path
- ✅ 3P legacy Akagi PTH: `(775,34)`, 44 actions, actual gameplay smoke
- ✅ legacy 3P 4-slot event normalization + hidden-information masking
- ✅ legacy Champion을 `akagi_legacy_champion.pth`로 분리하고 native 1010 slots 보존
- ✅ 3P legacy teacher mirror self-play 24 games → 23 train / 1 val → loader + GRP validation
- 🧪 4P population self-play local generation을 같은 수준까지 확대 검증 중
- 🧪 RTX 5080 실제 30-minute mixed production serving soak 미완료
- 🧪 Mortal vs ROGS vs ROGS+Global 장시간 strength 측정 미완료

---

# Architecture

```text
workspace/
├─ mortal-rogs/                     # repository / Control Center / tools
├─ Mortal_Unified/                  # managed runtime
│  ├─ .venv/
│  ├─ mortal/                       # canonical Mortal + managed patches
│  ├─ libriichi/                    # unified native/PyO3 source
│  ├─ compat/
│  │  └─ akagi-ng/
│  │     └─ lib/libriichi3p.*       # pinned legacy 3P encoder/Bot
│  └─ runtime/
│     ├─ 3p/
│     │  ├─ data/
│     │  ├─ models/
│     │  └─ runs/
│     ├─ 4p/
│     │  ├─ data/
│     │  ├─ models/
│     │  └─ runs/
│     ├─ serving-benchmarks/
│     └─ serving-profiles/
└─ Mortal_ROGS_Results/
```

다음은 mode 사이에서 공유하지 않습니다.

```text
training/validation data
current.pth
best_mortal.pth
baseline.pth
grp.pth
population.json
self-play state
experiment output
promotion state
```

---

# ABI / wire contracts

## 1. Native Mortal-ROGS training ABI

현재 active bootstrap + Rust encoder + manifest + CI가 맞추는 계약입니다.

| Contract | 3P Sanma | 4P Yonma |
|---|---:|---:|
| Players | 3 | 4 |
| Actions | 44 | 46 |
| Public observation | `(1010, 34)` | `(1012, 34)` |
| **Oracle observation** | **`(170, 34)`** | `(217, 34)` |
| GRP input | 6 | 7 |
| Chi | disabled | enabled |
| Nuki | enabled | disabled |
| Native evaluator | `OneVsTwo` | `OneVsThree` |

> [!IMPORTANT]
> 과거 metadata 일부가 3P Oracle을 217로 잘못 적고 있었지만 실제 bootstrap과 Stage4C native encoder는 **170**입니다. 현재 manifest/test도 170으로 정렬되고 cross-source consistency test가 이를 잠급니다.

## 2. AkagiOT wire ABI

Untouched Akagi-NG는 자신의 encoder가 만든 public observation과 legal mask를 HTTP server로 보냅니다.

| Mode | Endpoint | Wire obs | Actions | Encoder |
|---|---|---:|---:|---|
| 3P | `/react_batch_3p` | **`(775,34)`** | 44 | pinned Akagi `libriichi3p` v4 |
| 4P | `/react_batch` | `(1012,34)` | 46 | pinned Akagi `libriichi` v4 |

Request:

```json
{"obs": [...], "masks": [...]}
```

Response:

```json
{"actions": [...], "q_out": [...], "masks": [...], "is_greedy": [...]}
```

3P의 775는 단순 상수가 아니라 pinned `libriichi3p.mjai.Bot` wire probe를 통해 실제 engine callback tensor shape으로 검증합니다.

## 3. Mortal v4 compatibility checkpoint ABI

현재 `serving/inference.py`의 **Mortal backend**는 다음 구조를 요구합니다.

```text
config
mortal
current_dqn
```

그리고 version 4 `Brain` / `DQN`을 생성합니다.

이 제약은 **현재 server backend의 구현 선택**이지 AkagiOT 자체의 요구사항이 아닙니다. 따라서 future Mortal-ROGS-native backend가 다른 checkpoint/model architecture를 사용하더라도 정확한 Akagi wire ABI를 소비하고 응답 contract를 만족한다면 Akagi-NG와 연동할 수 있습니다.

## 3P native 1010 vs Akagi wire 775

두 encoding은 semantic layout이 다릅니다.

```text
native research/training: 1010 × 34
untouched Akagi wire:       775 × 34
```

금지:

```text
zero-padding 775 → 1010
weight reshape
channel copy without semantic mapping
```

현재 가능한 방향:

1. exact 775 wire representation으로 deployment model 학습
2. **1010 research/teacher → 775 deployment student distillation**
3. Akagi protocol 자체를 raw/MJAI state로 변경 — vanilla Akagi 목표와 충돌하므로 현재 비선호

현재는 2번을 우선 가설로 두되 구현 완료로 주장하지 않습니다.

### Existing legacy 775 bridge

```text
Unified OneVsTwo
      ↓ full internal MJAI
legacy event adapter
  ├─ 3-seat vector → 4-slot historical container
  ├─ opponents' initial hands → '?'
  └─ opponents' tsumo → '?'
      ↓
pinned libriichi3p.mjai.Bot
      ↓
775 observation / 44 actions
      ↓
legacy Mortal-compatible checkpoint
```

Legacy Champion은:

```text
runtime/3p/models/akagi_legacy_champion.pth
```

에 설치하며 native:

```text
current.pth
best_mortal.pth
baseline.pth
```

를 덮어쓰지 않습니다.

See: [`docs/ABI_AND_WIRE_CONTRACTS.md`](docs/ABI_AND_WIRE_CONTRACTS.md)

---

# Mortal-ROGS training

## Canonical active path

```text
train.py
  ↓
FileDatasetsIter
  ↓
GRP / RewardCalculator
  ↓
Mortal baseline OR ROGS composite objective
  ↓
optimizer
  ↓
checkpoint
```

## ROGS active components

현재 canonical ROGS path:

- value Huber loss
- chosen-action sampled advantage / regret-like regression
- offline BC anchor
- offline CQL anchor
- entropy regularization
- curriculum weights
- mode-aware GRP reward
- optional score-delta global reward
- global reward default **OFF**

ROGS는 formal CFR 구현이 아닙니다. chosen action에 대한 sampled residual을 regret-like signal로 이용하는 ACH/LuckyJ-inspired heuristic입니다.

### Ablation semantics

`mortal`, `rogs`, `rogs-global`은 동일 data/seed/architecture/optimizer/budget를 사용하는 비교지만 **regret 하나의 factorial ablation은 아닙니다.**

Stock Mortal:

```text
chosen-Q MSE
+ CQL × min_q_weight (upstream example: 5)
+ next-rank auxiliary
```

ROGS:

```text
value
+ regret-like regression
+ BC
+ ROGS CQL curriculum
- entropy
+ next-rank auxiliary
(+ optional global reward data target)
```

따라서 run manifest에 다음을 저장합니다.

- `comparison_scope = composite-algorithm`
- objective family
- stock CQL coefficient
- ROGS base/final coefficients
- Oracle/Search/Hedge active 여부

## ROGS telemetry

장시간 실험 해석을 위해 TensorBoard에 다음을 기록합니다.

- total/value/regret
- BC/CQL/entropy
- Oracle/Search component (현재 canonical path에서는 availability=0)
- raw components
- weighted contributions
- effective curriculum coefficients
- regret target mean/std
- clipping fraction
- legal action count
- oracle/search availability
- 기존 Q prediction/target histograms

## Oracle / Search

Objective API는 `oracle_q`와 `search_q`를 받을 수 있고 KL helper도 존재합니다.

하지만 **현재 canonical trainer는 teacher tensor를 생성하거나 전달하지 않습니다.** 따라서 Oracle/Search는 active production learning component로 주장하지 않습니다.

## Hedge

`hedge_policy()`와 `hedge_eta` config는 존재하지만 **현재 canonical self-play behavior policy는 이를 호출하지 않습니다.** 먼저 baseline strength와 telemetry를 측정한 뒤 controlled exploration이 필요할 때 연결합니다.

## Potential shaping

현재 base Mortal GRP reward 자체가:

```text
expected rank utility(next)
-
expected rank utility(previous)
```

형태의 potential difference입니다.

반면 `training.rogs.potential_shaped_reward(..., gamma=...)`는 별도 configurable experiment helper이며 **canonical trainer에서 호출되지 않습니다.** 둘을 같은 기능으로 표현하지 않습니다.

## Q-as-logit calibration

BC/entropy/optional teacher KL은 Q-derived scores를 policy logits처럼 사용합니다. 이것은 현재 즉시 correctness bug로 판정하지 않습니다. 다만 Q scale 변화가 regularizer의 effective temperature에 영향을 줄 수 있으므로 long-run telemetry를 먼저 보고 explicit temperature/normalized advantage 실험이 필요한지 결정합니다.

## Design-only hybrid configs

다음 파일은 canonical runtime config가 아닙니다.

```text
config/hybrid_rogs_v4.toml
config/hybrid_rogs_v4_multi.toml
```

둘 다 `status.design_only = true`, `active_runtime = false`로 표시합니다.

Active overlay:

```text
config/rogs_runtime.toml
```

See: [`docs/HYBRID_PARADIGM.md`](docs/HYBRID_PARADIGM.md)

---

# Training data

세 경로를 지원합니다.

1. **Population self-play** — external human logs 없이 시작 가능
2. **Mahjong Soul local preparation**
3. **Tenhou local preparation**

권장 synthetic-first 흐름:

```text
strong existing checkpoint(s)
        ↓
population validation
        ↓
local Mortal/libriichi self-play
        ↓
MJAI train / val
        ↓
GRP + learner
        ↓
Champion / learner / history cross-play
        ↓
duplicate evaluation
        ↓
gated promotion
```

> [!WARNING]
> 현재 `generate ... activate`는 해당 mode의 Mortal/GRP dataset config를 `selfplay-population` root로 지정합니다. **Tenhou/Mahjong Soul + self-play 비율 자동 혼합은 아직 구현되지 않았습니다.**

## Mahjong Soul

Implemented preparation:

- Amae-Koromo metadata discovery
- 3P `pl3`, 4P `pl4`
- 3P Sanma Throne → Jade → Gold
- 4P Throne → Jade → Gold
- discovery max 4 requests/sec
- record-cap window subdivision
- resumable cache/journal
- authenticated local record download
- pinned converter
- 3P north → MJAI `nukidora`
- deterministic split
- GameplayLoader + GRP validation
- mode-specific GRP preparation
- credentials not persisted to Git/config/result files

Pinned converter:

```text
NikkeTryHard/tenhou-to-mjai
69fb75a51c7efef3212be603227b2a58a9717237
```

```powershell
.\RUN_MAJSOUL_FULL.bat prepare 5000 5000 authorized 10000 en
```

> Child-process command-line handling can transiently expose credentials to local process-inspection tools. See detailed documentation before real credential operation.

See: [`docs/MAJSOUL_TRAINING_PREP.md`](docs/MAJSOUL_TRAINING_PREP.md)

## Tenhou

| Purpose | Tool | Pin |
|---|---|---|
| Houou download/cache | `Apricot-S/houou-logs` | `d4ca693771517b67172521f2bd76517500db4a6e` |
| 3P XML → MJAI | `Mateces/tenhou-sanma-to-mjai` | `e0bd7bffe24227f97600c710cffa4490117b634a` |
| 4P XML → MJAI | `Jim137/mjlog2mjai` | `c133f7dbf61046feaf1af72369d9a44056807657` |

```powershell
.\RUN_TENHOU_FULL.bat prepare 5000 5000 authorized 10000
```

Implemented:

- separate converters per mode
- deterministic 95/5 split
- loader + GRP validation
- converter error-ratio gate
- cache/resume
- no downloaded logs committed to Git

Historical archive availability is not treated as guaranteed.

See: [`docs/TENHOU_TRAINING_PREP.md`](docs/TENHOU_TRAINING_PREP.md)

---

# Population self-play

## Prepare

3P:

```powershell
.\RUN_SELFPLAY_POPULATION.bat prepare 3p "D:\models\sanma.pth"
```

4P:

```powershell
.\RUN_SELFPLAY_POPULATION.bat prepare 4p `
  "D:\models\verified-4p.pth" `
  "D:\models\other-4p.pth"
```

Validation gates:

1. SHA-256 identify/deduplicate
2. mode / observation ABI detection
3. checkpoint load/forward
4. actual `OneVsTwo` / `OneVsThree` gameplay smoke
5. accepted-only population copy
6. rejected reason manifest
7. compatible Champion slot installation
8. legacy 775/native 1010 slot separation

Manifests:

```text
runtime/3p/models/population/population.json
runtime/4p/models/population/population.json
```

## Generate

Small smoke:

```powershell
.\RUN_SELFPLAY_POPULATION.bat generate 3p 24
.\RUN_SELFPLAY_POPULATION.bat generate 4p 32
```

Scale after smoke:

```powershell
.\RUN_SELFPLAY_POPULATION.bat generate 3p 1000 activate
.\RUN_SELFPLAY_POPULATION.bat generate 4p 1000 activate
```

Behavior:

- resumable seed/batch state
- 3P challenger 1 vs Champion 2 + seat rotation
- 4P challenger 1 vs Champion 3 + seat rotation
- one member → mirror self-play
- multiple members → bidirectional cross-play + Champion mirror
- MJAI header/player-count validation
- deterministic train/val assignment
- GameplayLoader + GRP validation before success
- interrupted file reuse accounting

Data:

```text
runtime/3p/data/selfplay-population/{train,val}/
runtime/4p/data/selfplay-population/{train,val}/
```

State:

```text
runtime/3p/runs/selfplay-data/state-3p.json
runtime/4p/runs/selfplay-data/state-4p.json
```

See: [`docs/POPULATION_SELFPLAY.md`](docs/POPULATION_SELFPLAY.md)

---

# Evaluation & promotion

## Canonical backends

현재 실제 model-comparison/promotion source-of-truth:

| Backend | Mode | Role | Status |
|---|---:|---|---|
| `libriichi3p` / unified arena | 3P | canonical correctness/promotion | ✅ |
| `libriichi` | 4P | canonical correctness/promotion | ✅ |
| `mjx` | 4P | explicit high-throughput parity/throughput experiment | 🧪 |
| `mjx_sanma` | 3P | experimental parity project | 🧪 |
| `mjai` | 4P | legacy cross-check | reference |

`select_backend(..., preference="auto")`는 현재 3P `libriichi3p`, 4P `libriichi`를 선택합니다. MJX는 parity/cross-check를 실제 promotion runner에 연결하기 전에는 자동 승격 경로로 사용하지 않습니다.

## Duplicate protocol

| Mode | Seats per seed | Match |
|---|---:|---|
| 3P | A / B / C | Challenger 1 vs Champion 2 |
| 4P | A / B / C / D | Challenger 1 vs Champion 3 |

Top-level comparison은 같은 seed range/key로:

```text
Candidate → Baseline
Baseline  → Candidate
```

둘 다 사용합니다.

## Seed-cluster bootstrap

같은 seed의 seat rotations는 독립 iid sample이 아니므로 **seed 단위 cluster**로 bootstrap합니다.

```text
seed 10000
  ├─ seat 0
  ├─ seat 1
  └─ seat 2/3
      = one resampling cluster
```

Gate 입력은 seed마다 모든 seat가 존재해야 합니다. 누락 rotation이 있으면 promotion gate가 거부합니다.

Output에는:

```text
bootstrap_unit = seed-cluster
seed_clusters
metric.clusters
```

가 기록됩니다.

## Outputs

```text
runtime/<mode>/runs/comparison/<name>/
├─ candidate-vs-baseline/
├─ baseline-vs-candidate/
├─ paired.jsonl
├─ paired.summary.json
├─ paired.summary.md
├─ native-stat.json
├─ native-stat.txt
├─ promotion-gate.json
└─ comparison.json
```

Metrics:

- placement distribution
- average rank
- tobi / last-place
- raw score delta
- rank points
- platform rating utility
- seed-cluster bootstrap CI
- agari / houjuu / riichi / fuuro / ryukyoku
- native `libriichi.Stat`

`--seed-count 100`은 preview이며 작은 strength 차이의 production promotion proof가 아닙니다.

See: [`docs/MODEL_COMPARISON.md`](docs/MODEL_COMPARISON.md)

---

# Rating-aware objectives

플랫폼마다 같은 순위/최종점수의 ladder value가 다르므로 training/evaluation utility를 profile로 분리합니다.

```text
Mahjong public observation ─────────────> model
                                            │
platform / room / rank / result ─> utility ┘  training/evaluation only
```

`training/rating_router.py`:

- **Universal** — mode별 objective mixture
- **Specialized** — target profile fine-tune
- **Curriculum** — universal → target 비중 증가

Configs:

```text
config/rating_presets.toml
config/rating_contexts.toml
```

현재 model observation에 platform context를 자동 삽입하지 않습니다. 따라서 실용적인 방법은 objective mixture, specialized fine-tune, profile별 checkpoint selection입니다.

See: [`docs/RATING_PRESETS_AND_DUAL_MODE.md`](docs/RATING_PRESETS_AND_DUAL_MODE.md)

---

# Akagi-NG API serving

## Architecture

```text
untouched Akagi-NG
       │
       │ gzip HTTP + Authorization
       │ obs / masks
       ▼
Mortal-ROGS inference API
       │
       │ current model backend
       ▼
actions / q_out / masks / is_greedy
```

하지 않는 것:

- Mortal-ROGS checkpoint를 Akagi-NG model directory에 복사
- Akagi-NG source patch
- Akagi-NG가 Mortal-ROGS `.pth` 직접 `torch.load`
- Control Center에서 Akagi install path 요구

Direct export tooling은 intentionally deprecated/disabled입니다.

## Current serving backend vs protocol

`serving/inference.py`는 현재 Mortal v4 compatibility checkpoint loader를 구현합니다. 즉 현재 server backend는 Mortal-specific이지만 **AkagiOT protocol은 Mortal-specific이 아닙니다.**

### 3P deployment gap

Untouched Akagi 3P wire는 775이고 native learner는 1010입니다. 따라서 현재 synthetic 1010 AkagiOT smoke를 full real deployment proof로 해석하지 않습니다.

현재 audit/CI는:

- pinned 775 const contract
- actual `libriichi3p.mjai.Bot` callback tensor probe
- HTTP client protocol

를 분리해서 검증합니다.

다음 serving correctness 단계는 **775-compatible 3P deployment backend/student를 실제 HTTP server에 연결하고 Bot→HTTP→server 전체 E2E를 검증하는 것**입니다.

## Timing / resilience

Pinned AkagiOT:

```text
connect timeout     2 s
read timeout        4 s
failure threshold   3
recovery            30 s
```

Server default deadline:

```text
3500 ms
```

으로 client read timeout보다 먼저 실패하게 합니다.

## Implemented serving reliability

- separate 3P/4P slots
- background hot reload
- warmup before atomic publish
- last-known-good
- degraded state on bad replacement
- dynamic micro-batching
- bounded queue/backpressure
- request deadline
- graceful drain/stop/restart
- Windows Ctrl+Break handling
- serialized maintenance
- reload quiet window
- shared GPU forward coordination
- RTX profile `max_device_executions=1`
- latency/queue/CUDA allocator telemetry
- benchmark/A-B sweep
- mixed-mode soak
- production profile transaction
- apply verification / rollback / persisted recovery
- API key runtime-only handling

Management endpoints:

```text
GET  /api/inference/health
GET  /api/inference/models
GET  /api/inference/metrics
POST /api/inference/3p
POST /api/inference/4p
POST /api/inference/reload
POST /api/inference/production/apply
POST /api/inference/production/start
GET  /api/inference/production/status
```

## Production soak gate

```text
minimum duration       30 min
traffic                mixed 3P + 4P
concurrency            8
p95                     <= 100 ms
p99                     <= 250 ms
peak VRAM               <= 92%
GPU temperature         <= 88 C
busy/deadline/errors    0
NVIDIA telemetry        required
```

CI는 logic smoke만 수행하며 RTX 5080 production 수치를 만들어내지 않습니다.

See:

- [`docs/ABI_AND_WIRE_CONTRACTS.md`](docs/ABI_AND_WIRE_CONTRACTS.md)
- [`docs/AKAGI_API_INTEGRATION.md`](docs/AKAGI_API_INTEGRATION.md)
- [`docs/INFERENCE_SERVING.md`](docs/INFERENCE_SERVING.md)
- [`docs/RTX5080_SERVING_SOAK.md`](docs/RTX5080_SERVING_SOAK.md)
- [`docs/INFERENCE_PRODUCTION_PROFILE.md`](docs/INFERENCE_PRODUCTION_PROFILE.md)
- [`docs/INFERENCE_PRODUCTION_RECOVERY.md`](docs/INFERENCE_PRODUCTION_RECOVERY.md)

---

# Control Center

기존 JobManager / logs / stop workflow를 재사용합니다. 별도 experiment DB나 새 orchestration server를 만들지 않습니다.

현재 UI:

- unified runtime/bootstrap status
- mode selection 3P/4P
- config editing
- GRP training
- offline Mortal/ROGS training
- existing self-play flow
- TensorBoard
- checkpoint management
- evaluation/promotion
- ablation
- bidirectional model comparison
- Akagi inference lifecycle
- reload
- telemetry
- benchmark / A-B sweep / soak
- production profile apply/rollback/recovery
- GPU utilization / VRAM / temperature / power
- jobs/logs/stop

아직 UI에 정식 연결되지 않은 것:

```text
population checkpoint preparation
population self-play generation
```

현재 canonical entrypoint:

```text
RUN_SELFPLAY_POPULATION.bat
```

검증 후 기존 JobManager에 연결하며 새 DB/service를 추가하지 않습니다.

---

# Quick start

## Target environment

- Windows 10 / 11 x64
- NVIDIA GPU
- RTX 5080 16GB target preset
- Python 3.12
- CUDA 12.8
- PyTorch 2.11
- BF16
- `torch.compile`
- Windows Triton 3.6.x
- Rust / MSVC Build Tools

## Clone

```powershell
cd C:\Users\<사용자명>\Downloads

git clone --branch research/mortal-rogs-v4-impl --single-branch `
  https://github.com/gkfyddl2662/JSGomoku.git `
  mortal-rogs

cd .\mortal-rogs
```

Update:

```powershell
git pull
```

## Install + smoke

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\setup_and_smoke_unified_windows.ps1"
```

Custom root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\setup_and_smoke_unified_windows.ps1" `
  -InstallRoot "D:\Mortal_Unified"
```

Managed setup may perform:

- pinned Mortal checkout
- Python venv
- CUDA/PyTorch stack
- Rust/MSVC checks
- managed patch chain
- PyO3 build/install
- mode configs
- CUDA/BF16/compile smoke
- gameplay/log/loader/mini-training/evaluator/API/Control Center smoke

## Validation only

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\smoke_unified_windows.ps1" `
  -InstallRoot "C:\Users\<사용자명>\Downloads\Mortal_Unified"
```

## Control Center

```powershell
C:\Users\<사용자명>\Downloads\Mortal_Unified\.venv\Scripts\python.exe -m app.main
```

```text
http://127.0.0.1:8188
```

---

# Local experiments

Validate:

```powershell
.\RUN_LOCAL.bat validate
```

Ablation both modes:

```powershell
.\RUN_LOCAL.bat experiment fresh both
```

Single mode:

```powershell
.\RUN_LOCAL.bat experiment fresh 3p
.\RUN_LOCAL.bat experiment fresh 4p
```

Variants:

```text
mortal
rogs
rogs-global
```

Run policy:

```text
error   # default: refuse accidental existing checkpoint reuse
fresh   # selected isolated run only reset
resume  # explicit resume
```

Full workstation suite:

```powershell
.\RUN_LOCAL.bat full fresh both
```

Results:

```text
<workspace>\Mortal_ROGS_Results\YYYYMMDD-HHMMSS-*/
```

See: [`docs/LOCAL_WORKSTATION_RUN.md`](docs/LOCAL_WORKSTATION_RUN.md)

---

# Validation

## GitHub Actions

8 workflows:

| Workflow | Coverage |
|---|---|
| `research-ci.yml` | ROGS/rating/evaluation contracts |
| `unified-core-ci.yml` | patches/model/training contracts |
| `unified-runtime-ci.yml` | install/runtime/smoke |
| `unified-gameplay-contract-ci.yml` | actual native gameplay/evaluators |
| `libriichi-python-package-ci.yml` | PyO3 build/import/E2E |
| `akagi-api-contract-ci.yml` | untouched AkagiOT HTTP client contract |
| `akagi-3p-compat-ci.yml` | pinned 775 encoder/Bot/event/wire probe |
| `windows-script-ci.yml` | Windows orchestration |

Badge가 branch 최신 CI 상태를 표시하므로 README에 특정 HEAD의 `8/8 green` 문장을 고정하지 않습니다.

## CI checks

- pinned source / patch anchors / postconditions
- Rust compile/tests
- PyO3 build/import
- 3P Oracle 170 cross-source consistency
- native 3P/4P gameplay
- MJAI loader roundtrip
- GRP/reward
- mini-training
- strict checkpoint save/reload
- ROGS loss/gradient + telemetry diagnostics
- duplicate forward/reverse
- seed-cluster promotion bootstrap
- native Stat
- evaluation backend policy
- rating gate
- AkagiOT request/response/timing/resilience contract
- pinned 3P 775 Bot/event adapter
- actual pinned 3P Bot wire tensor probe
- serving scheduler/LKG/reload/soak/profile/rollback logic

## CI does not prove

- real 30-minute RTX 5080 p95/p99
- empirical ROGS strength improvement
- long-run training stability
- full 3P `Bot → HTTP → 775 deployment server backend` E2E until that backend is connected
- MJX parity for promotion
- full LuckyJ/Suphx reproduction

---

# Roadmap

## ✅ Implemented / corrected

- unified 3P/4P managed runtime
- native 1010/1012 training observations
- **3P Oracle 170 / 4P Oracle 217 source-of-truth alignment**
- mode-aware GRP
- ROGS composite objective
- ROGS component/effective-weight telemetry
- global reward implementation default OFF
- population checkpoint validation
- resumable population self-play
- legacy 775 3P teacher/opponent bridge
- hidden-information-safe 3P legacy event adapter
- duplicate bidirectional evaluation
- **seed-cluster bootstrap + complete-seat gate**
- native `libriichi.Stat`
- rating router/presets
- canonical native evaluation backend policy
- Akagi wire vs model ABI separation
- real pinned Akagi 3P wire probe
- dynamic serving / LKG / hot reload / production tooling

## 🚧 Highest-priority correctness / deployment work

1. **3P Akagi deployment backend** — exact 775 wire consumer, no 775→1010 fake transform
2. full `libriichi3p.mjai.Bot → AkagiOT HTTP → server → response` E2E
3. choose/measure **1010 teacher → 775 student distillation** vs direct 775 training
4. 4P population self-play local smoke/scale validation
5. 3P native learner bootstrap while keeping 775 deploy path separate
6. population Web UI wiring after CLI stability

## 🧪 Empirical work

1. Mortal / ROGS / ROGS+Global long runs
2. inspect raw/weighted component telemetry
3. statistically meaningful duplicate evaluation
4. RTX 5080 30-minute production serving soak
5. small permitted Mahjong Soul / Tenhou calibration set
6. platform-specific rating fine-tuning

## 🗺️ Add only if measurements justify it

- factorial controls such as stock+regret / ROGS with stock-equivalent CQL
- active Hedge exploration policy
- Oracle teacher generation/propagation
- Search teacher
- pMCP / amortized adaptation
- configurable human-log + self-play mixture
- advanced population sampling/snapshot pruning
- MJX production promotion backend after fixed-seed parity
- per-game dynamic rating context
- non-Mortal internal model architecture/backend

---

# Repository layout

```text
mortal-rogs/
├─ app/                         # Control Center backend/jobs/GPU/production
├─ static/                      # Control Center UI
├─ training/                    # mode, ROGS, objectives, rating
├─ evaluation/                  # backends, paired, gating, stats
├─ serving/                     # current inference backend, resilience, coordination
├─ config/                      # runtime/design/rating/backend presets
├─ mortal_unified/
│  └─ manifest.toml             # native mode contract metadata
├─ mjx_sanma/
│  └─ manifest.toml             # experimental MJX-Sanma policy
├─ scripts/                     # bootstrap/patch/data/eval/serving/self-play
├─ tests/                       # source/contract/regression tests
├─ docs/                        # design/operations documents
├─ .github/workflows/           # CI
├─ RUN_LOCAL.bat
├─ RUN_MAJSOUL_FULL.bat
├─ RUN_TENHOU_FULL.bat
├─ RUN_SELFPLAY_POPULATION.bat
└─ README.md
```

---

# Documentation

| Document | Purpose |
|---|---|
| [`ABI_AND_WIRE_CONTRACTS.md`](docs/ABI_AND_WIRE_CONTRACTS.md) | Akagi wire / native training / checkpoint ABI 분리 |
| [`AKAGI_API_INTEGRATION.md`](docs/AKAGI_API_INTEGRATION.md) | untouched Akagi API integration |
| [`INFERENCE_SERVING.md`](docs/INFERENCE_SERVING.md) | batching/deadline/reload/telemetry |
| [`INFERENCE_PRODUCTION_PROFILE.md`](docs/INFERENCE_PRODUCTION_PROFILE.md) | production profile transaction |
| [`INFERENCE_PRODUCTION_RECOVERY.md`](docs/INFERENCE_PRODUCTION_RECOVERY.md) | restart/recovery/drift |
| [`RTX5080_SERVING_SOAK.md`](docs/RTX5080_SERVING_SOAK.md) | 30-minute production gate |
| [`HYBRID_PARADIGM.md`](docs/HYBRID_PARADIGM.md) | ROGS/ACH/Suphx-inspired design |
| [`RATING_PRESETS_AND_DUAL_MODE.md`](docs/RATING_PRESETS_AND_DUAL_MODE.md) | rating objectives |
| [`MODEL_COMPARISON.md`](docs/MODEL_COMPARISON.md) | duplicate comparison/promotion |
| [`POPULATION_SELFPLAY.md`](docs/POPULATION_SELFPLAY.md) | population bootstrap/self-play |
| [`MAJSOUL_TRAINING_PREP.md`](docs/MAJSOUL_TRAINING_PREP.md) | Mahjong Soul preparation |
| [`TENHOU_TRAINING_PREP.md`](docs/TENHOU_TRAINING_PREP.md) | Tenhou preparation |
| [`LOCAL_WORKSTATION_RUN.md`](docs/LOCAL_WORKSTATION_RUN.md) | workstation orchestration |
| [`EVALUATION_BACKENDS.md`](docs/EVALUATION_BACKENDS.md) | native/MJX evaluator policy |

---

# Research boundaries

## What is active

- Mortal compatibility baseline
- ROGS value/regret/BC/CQL/entropy composite
- base GRP potential-difference reward
- optional score-delta global reward
- population self-play
- native duplicate evaluation
- rating utility foundation

## What is not active in canonical learning

- Oracle teacher tensor generation/propagation
- Search teacher tensor generation/propagation
- Hedge behavior sampling
- standalone `potential_gamma` helper path
- runtime pMCP/amortized pMCP
- full CFR/search recreation

## Claims not made

- ACH Nash guarantees for multiplayer Mahjong
- full LuckyJ reproduction
- full Suphx reproduction
- ROGS > Mortal before measured duplicate results
- MJX promotion correctness before parity
- 1010 native 3P model is directly compatible with untouched Akagi 775 wire

Terminology:

```text
LuckyJ/ACH-inspired
Suphx-inspired
Mortal v4 compatibility backend
AkagiOT wire ABI
native training ABI
```

## Data / authorization

- external logs are not redistributed in this repository
- use Mahjong Soul/Tenhou records only within applicable permissions
- `authorized` argument is a local acknowledgement, not a license grant
- credentials are not committed to Git

## Backups

Back up valuable local artifacts independently:

```text
Mortal_Unified/runtime/<mode>/models/
Mortal_Unified/runtime/<mode>/data/
Mortal_ROGS_Results/
```

---

# Legacy migration

Recommended layout: `Mortal_Unified`.

Legacy tooling such as:

```text
scripts/migrate_legacy_runtime.ps1
```

exists for older layouts and is not the preferred fresh setup path.

Direct Akagi checkpoint export:

```text
scripts/export_akagi_mortal.py
```

is intentionally disabled because Akagi-NG is an API client in the current architecture.

---

# Troubleshooting

## `fatal: not a git repository`

```powershell
cd C:\Users\<사용자명>\Downloads\mortal-rogs
Test-Path .\.git
```

Expected: `True`.

## `ModuleNotFoundError: libriichi`

```powershell
C:\Users\<사용자명>\Downloads\Mortal_Unified\.venv\Scripts\python.exe `
  -c "import libriichi; print(libriichi.__file__)"
```

Managed PyO3 submodules use parent imports:

```python
from libriichi import consts
from libriichi import stat
from libriichi import arena
```

## 3P checkpoint has 775 channels

Do not convert it to 1010 by padding. Treat it as legacy/Akagi-wire-compatible 775 and use the compatibility population/evaluation path.

## 3P checkpoint has 1010 channels

It is native Mortal-ROGS training/evaluation ABI. Do not assume it can be served to untouched Akagi-NG until a correct 775 deployment strategy is present.

## `TritonMissing`

```powershell
git pull
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\smoke_unified_windows.ps1"
```

## MSVC / `link.exe`

Install Visual Studio 2022 Build Tools:

```text
Desktop development with C++
```

## CUDA OOM

Reduce training batch progressively:

```text
512 → 384 → 256 → 128
```

Serving tuning should consider queue/deadline/micro-batch/VRAM together.

## Population self-play failure

Inspect:

```text
runtime/<mode>/models/population/population.json
runtime/<mode>/runs/selfplay-data/state-<mode>.json
runtime/<mode>/runs/selfplay-data/generation-*.json
```

---

<div align="center">

### Development branch

`research/mortal-rogs-v4-impl`

**Correctness first · 3P and 4P always separate · Mortal compatible, not Mortal-constrained**

</div>
