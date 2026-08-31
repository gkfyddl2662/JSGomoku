<div align="center">

# Mortal-ROGS

### Unified Mortal v4 Research · Training · Evaluation · Serving for 3P & 4P Riichi Mahjong

**Windows에서 3인마작(Sanma)과 4인마작(Yonma) Mortal AI를 하나의 런타임과 Control Center로 설치·학습·평가·운영하는 연구 플랫폼**

[![Research CI](https://github.com/gkfyddl2662/JSGomoku/actions/workflows/research-ci.yml/badge.svg?branch=research%2Fmortal-rogs-v4-impl)](https://github.com/gkfyddl2662/JSGomoku/actions/workflows/research-ci.yml)
[![Unified Runtime CI](https://github.com/gkfyddl2662/JSGomoku/actions/workflows/unified-runtime-ci.yml/badge.svg?branch=research%2Fmortal-rogs-v4-impl)](https://github.com/gkfyddl2662/JSGomoku/actions/workflows/unified-runtime-ci.yml)
[![Gameplay Contract](https://github.com/gkfyddl2662/JSGomoku/actions/workflows/unified-gameplay-contract-ci.yml/badge.svg?branch=research%2Fmortal-rogs-v4-impl)](https://github.com/gkfyddl2662/JSGomoku/actions/workflows/unified-gameplay-contract-ci.yml)
[![Akagi API](https://github.com/gkfyddl2662/JSGomoku/actions/workflows/akagi-api-contract-ci.yml/badge.svg?branch=research%2Fmortal-rogs-v4-impl)](https://github.com/gkfyddl2662/JSGomoku/actions/workflows/akagi-api-contract-ci.yml)
[![Akagi 3P Compatibility](https://github.com/gkfyddl2662/JSGomoku/actions/workflows/akagi-3p-compat-ci.yml/badge.svg?branch=research%2Fmortal-rogs-v4-impl)](https://github.com/gkfyddl2662/JSGomoku/actions/workflows/akagi-3p-compat-ci.yml)
[![Windows Script CI](https://github.com/gkfyddl2662/JSGomoku/actions/workflows/windows-script-ci.yml/badge.svg?branch=research%2Fmortal-rogs-v4-impl)](https://github.com/gkfyddl2662/JSGomoku/actions/workflows/windows-script-ci.yml)

**Mortal v4** · **Python 3.12** · **PyTorch 2.11 / CUDA 12.8** · **BF16** · **torch.compile** · **RTX 5080 target**

</div>

> [!IMPORTANT]
> 이 저장소는 현재 **연구/개발 브랜치**입니다. 배포 ABI는 Mortal v4로 고정하며, 3P와 4P는 같은 코드/가상환경을 사용하되 **설정·데이터·GRP·체크포인트·실험 결과를 서로 섞지 않습니다.**

> [!NOTE]
> Branch: `research/mortal-rogs-v4-impl`  
> Canonical Mortal: `0cff2b52982be5b1163aa9a62fb01f03ce91e0d2`  
> Akagi-NG compatibility reference: `11c0ffc0d70bf8142585b92405b4412976c9e205`

---

## Contents

- [Overview](#overview)
- [Status](#status)
- [Architecture](#architecture)
- [3P / 4P ABI contracts](#3p--4p-abi-contracts)
- [Mortal-ROGS training](#mortal-rogs-training)
- [Training data](#training-data)
- [Population self-play](#population-self-play)
- [Evaluation backends](#evaluation-backends)
- [Model comparison & promotion](#model-comparison--promotion)
- [Rating-aware objectives](#rating-aware-objectives)
- [Akagi-NG API serving](#akagi-ng-api-serving)
- [Control Center](#control-center)
- [Quick start](#quick-start)
- [Local experiments](#local-experiments)
- [Validation](#validation)
- [Roadmap](#roadmap)
- [Repository layout](#repository-layout)
- [Documentation](#documentation)
- [Research / safety boundaries](#research--safety-boundaries)
- [Legacy migration](#legacy-migration)
- [Troubleshooting](#troubleshooting)

---

# Overview

Mortal-ROGS는 **Mortal v4 checkpoint 호환성을 유지하면서** 3P/4P 양쪽에서 데이터 준비, GRP, Mortal/ROGS 학습, population self-play, duplicate evaluation, rating-aware promotion, AkagiOT serving까지 하나의 연구/운영 흐름으로 묶는 프로젝트입니다.

```text
                              Mortal-ROGS
                                   │
         ┌─────────────────────────┼──────────────────────────┐
         │                         │                          │
   Data / Training           Evaluation                  Serving
         │                         │                          │
   ┌─────┴─────┐           ┌──────┴──────┐            ┌──────┴──────┐
   │           │           │             │            │             │
3P Sanma    4P Yonma    duplicate     rating gate  AkagiOT 3P   AkagiOT 4P
   │           │           │             │            │             │
   └──────┬────┘           └──────┬──────┘            └──────┬──────┘
          │                       │                          │
          └──────────────── Mortal_Unified ──────────────────┘
                                  │
                 one Mortal source / one .venv / one PyO3 stack
                                  │
                    ┌─────────────┴─────────────┐
                    │                           │
              runtime/3p                  runtime/4p
           data / models / runs        data / models / runs
```

## Design principles

| Principle | Contract |
|---|---|
| **Mortal v4 stays deployable** | 최종 student는 기존 `Brain + current_dqn` 구조를 유지합니다. |
| **3P and 4P stay separate** | 공통 알고리즘을 써도 weight/checkpoint/data는 mode별입니다. |
| **Teacher complexity, student simplicity** | GRP/Oracle/Search/Regret 아이디어가 배포 observation ABI를 늘리지 않습니다. |
| **Gameplay, not tensor-only smoke** | arena → MJAI → loader → train → checkpoint → evaluator를 실제로 확인합니다. |
| **No promotion by training loss** | duplicate/rating gate를 통과한 모델만 Champion/Best 후보가 됩니다. |
| **Akagi-NG is an API client** | Mortal-ROGS 모델 파일을 Akagi-NG에 복사하거나 직접 로드시키지 않습니다. |
| **Serving is feature-frozen** | 새 serving subsystem보다 correctness/reliability 수정이 우선입니다. |
| **No invented benchmark claims** | CI smoke를 RTX 5080 production 성능으로 해석하지 않습니다. |

---

# Status

상태 표시는 README 전체에서 동일하게 사용합니다.

- ✅ **Implemented / validated** — 구현되어 CI 또는 실제 smoke로 검증됨
- 🧪 **Implemented / measuring** — 기능은 있으나 장시간·대량·실성능 검증이 더 필요함
- 🚧 **In progress** — 현재 연결/확장 중
- 🗺️ **Planned / research** — 방향은 정했지만 완료 구현으로 주장하지 않음

## Feature matrix

| Area | 3P | 4P | Notes |
|---|---:|---:|---|
| Unified Mortal/Python runtime | ✅ | ✅ | `Mortal_Unified` 하나 |
| Mode-isolated config/data/models/runs | ✅ | ✅ | checkpoint tensor 공유 없음 |
| Native Mortal v4 training ABI | ✅ | ✅ | 1010ch / 1012ch |
| Native gameplay evaluator | ✅ | ✅ | `OneVsTwo` / `OneVsThree` |
| MJAI → `GameplayLoader` roundtrip | ✅ | ✅ | 실제 generated log 검증 |
| Mode-specific GRP | ✅ | ✅ | input width 6 / 7 |
| Mortal / ROGS / ROGS+Global ablation | ✅ | ✅ | Global reward default OFF |
| Bidirectional duplicate comparison | ✅ | ✅ | same seeds + full seat rotation |
| Native `libriichi.Stat` reporting | ✅ | ✅ | tactical metrics 포함 |
| Rating utility / preset router | ✅ | ✅ | universal/specialized/curriculum logic |
| Population checkpoint validation | ✅ | ✅ | real evaluator smoke 포함 |
| Population self-play generator | ✅ | ✅ | resumable CLI/BAT |
| Akagi legacy 775 teacher bridge | ✅ | — | 3P population/eval path only |
| AkagiOT-compatible HTTP API | ✅ | ✅ | `/react_batch_3p` / `/react_batch` |
| Dynamic batching / LKG / hot reload | ✅ | ✅ | shared-device coordination 포함 |
| Benchmark / soak / production profile / rollback | ✅ | ✅ | 실제 30분 RTX gate는 🧪 |
| Control Center core workflows | ✅ | ✅ | training/eval/serving/experiments |
| Population self-play Web UI wiring | 🚧 | 🚧 | 현재 BAT/CLI가 canonical entrypoint |
| Human-log + self-play automatic mixture | 🗺️ | 🗺️ | 현재 `activate`는 self-play root 직접 지정 |
| High-throughput MJX evaluation | 🧪 | ✅* | 3P parity-gated; 4P backend registered, WSL/Linux 필요 |
| Privileged Oracle distillation | 🗺️ | 🗺️ | Suphx-inspired future work |
| Search teacher / amortized pMCPA | 🗺️ | 🗺️ | deployment ABI 유지 전제 |
| Full LuckyJ neural CFR/search reproduction | 🗺️ | 🗺️ | 재현을 주장하지 않음 |

`✅*` 4P MJX는 evaluation backend registry의 high-throughput primary 선택지입니다. **Mortal/libriichi native path는 계속 correctness/reference 및 현재 population/duplicate 검증의 기준**으로 유지합니다.

## Confirmed local validation

현재 실제 Windows target workstation에서 확인된 범위:

- ✅ RTX 5080에서 unified 3P/4P runtime, CUDA, BF16, `torch.compile`
- ✅ 3P/4P gameplay, MJAI reload, mini-training, strict checkpoint reload, evaluator
- ✅ 4P Mortal v4 checkpoint population validation 및 Champion 설치 경로
- ✅ Akagi legacy 3P `775 × 34`, 44-action checkpoint actual gameplay smoke
- ✅ legacy 775 Champion을 native 1010 training slots와 분리 설치
- ✅ legacy 3P event adapter의 4-slot normalization + hidden-information masking
- ✅ legacy 775 teacher mirror self-play 24게임 생성, 23 train / 1 val, loader + GRP validation
- 🧪 4P population self-play의 별도 local generation/장시간 run 확대 검증 중
- 🧪 실제 RTX 5080 30분 mixed production serving soak 미완료
- 🧪 장시간 Mortal vs ROGS vs ROGS+Global strength 실측 미완료

---

# Architecture

```text
workspace/
├─ mortal-rogs/                     # repository / Control Center / tools
├─ Mortal_Unified/                  # managed runtime
│  ├─ .venv/
│  ├─ mortal/                       # pinned canonical Mortal + managed patches
│  ├─ libriichi/                    # unified PyO3/Rust source
│  ├─ compat/
│  │  └─ akagi-ng/                  # pinned legacy 3P compatibility binary
│  └─ runtime/
│     ├─ 3p/
│     │  ├─ config.toml
│     │  ├─ data/
│     │  ├─ models/
│     │  └─ runs/
│     ├─ 4p/
│     │  ├─ config.toml
│     │  ├─ data/
│     │  ├─ models/
│     │  └─ runs/
│     ├─ serving-benchmarks/
│     └─ serving-profiles/
└─ Mortal_ROGS_Results/             # workstation experiment results
```

다음 항목은 mode 사이에서 공유하지 않습니다.

```text
data
current.pth
best_mortal.pth
baseline.pth
grp.pth
population.json
experiment runs
promotion state
```

---

# 3P / 4P ABI contracts

## Native training ABI

현재 **실제 manifest + unified consts patch + tests 기준** 계약입니다.

| Contract | 3P Sanma | 4P Yonma |
|---|---:|---:|
| Mortal version | 4 | 4 |
| Players | 3 | 4 |
| Actions | 44 | 46 |
| Observation v4 | `(1010, 34)` | `(1012, 34)` |
| Oracle observation v4 | `(217, 34)` | `(217, 34)` |
| GRP input | 6 | 7 |
| Chi | disabled | enabled |
| Nuki | enabled | disabled |
| Native evaluator | `OneVsTwo` | `OneVsThree` |
| Historical deploy filename | `mortal3p.pth` | `mortal.pth` |

> [!IMPORTANT]
> 3P oracle shape는 현재 코드 계약상 **`(217, 34)`** 입니다. README/설계 메모보다 `mortal_unified/manifest.toml`, unified consts patch, `training/game_mode.py`, CI contract test를 source of truth로 봅니다.

3P/4P weights를 tensor 단위로 합치거나 한 physical checkpoint가 두 mode를 동시에 표현하게 만들지 않습니다.

## Akagi legacy 3P ABI

Akagi-NG/Mortal-Sanma 계열의 기존 3P checkpoint에는 native unified 1010ch와 다른 ABI가 존재합니다.

```text
Observation: (775, 34)
Actions:     44
Encoder:     pinned Akagi-NG libriichi3p
Checkpoint:  Mortal v4 family
```

775 weight를 1010에 padding/reshape하지 않습니다. 두 feature layout의 semantic이 동일하지 않기 때문입니다.

```text
Unified OneVsTwo arena
        │
        │ full internal MJAI
        ▼
Legacy event adapter
  ├─ 3-seat arrays → historical 4-slot containers
  ├─ opponent start hands → '?' masked
  └─ opponent tsumo tile  → '?' masked
        │
        ▼
pinned libriichi3p.mjai.Bot
        │
        ▼
775-channel public observation / 44 actions
        │
        ▼
legacy checkpoint
```

### Legacy bridge safety rules

- legacy Champion: `runtime/3p/models/akagi_legacy_champion.pth`
- native `current.pth`, `best_mortal.pth`, `baseline.pth`는 보존
- legacy 775는 현재 **population teacher/opponent/evaluation bridge** 용도
- managed Akagi-facing 3P serving ABI를 775로 조용히 바꾸지 않음
- legacy teacher가 생성한 **game log는 표준 MJAI**이므로 native 1010 learner의 `GameplayLoader`가 학습 가능

---

# Mortal-ROGS training

ROGS는 Mortal v4 network/deployment format을 유지하면서 regret/advantage 및 game-level reward를 실험하는 학습 경로입니다.

## Implemented training hooks

- canonical Mortal value/Q path 유지
- CQL baseline behavior 유지
- centered advantage / regret-style ROGS objective
- Hedge-policy exploration hook
- BC/CQL anchor
- online/offline curriculum hooks
- mode-aware GRP / reward path
- 3P rank reward `[6, 0, -6]`
- optional global reward shaping
- **global reward default OFF**
- fair ablation: `mortal`, `rogs`, `rogs-global`
- 동일 base config / dataset / seed / architecture / optimizer / budget
- default experiment training seed `36887` (`0x9017`)

```text
train.py
   ↓
FileDatasetsIter
   ↓
GRP / RewardCalculator
   ↓
Mortal baseline OR ROGS objective
   ↓
optimizer
   ↓
ordinary Mortal v4 checkpoint
```

## LuckyJ / ACH-inspired scope

Actor-Critic Hedge의 sampled advantage/regret와 Hedge policy 아이디어를 **self-play optimization heuristic**으로 차용합니다.

ACH의 Nash-convergence motivation은 2-player zero-sum 조건에 대한 것이므로 3P/4P Mahjong에서 동일한 보장을 주장하지 않습니다.

## Suphx-inspired scope

현재 실제 구현으로 주장하는 것은 **GRP + optional global reward shaping**입니다.

다음은 연구/향후 작업입니다.

- privileged Oracle teacher distillation
- sparse Search teacher distillation
- runtime pMCPA
- amortized pMCPA

## Deployment rule

학습 checkpoint에 optimizer/teacher/GRP/league metadata가 존재할 수 있어도 배포 student의 핵심 parameter는 기존 Mortal 형식을 유지합니다.

```text
config
mortal
current_dqn
```

Training-only parameter를 `mortal` 또는 `current_dqn`에 억지로 합치지 않습니다.

See: [`docs/HYBRID_PARADIGM.md`](docs/HYBRID_PARADIGM.md)

---

# Training data

세 경로를 지원합니다.

1. **Population self-play** — 외부 human logs 없이 시작 가능
2. **Mahjong Soul local preparation** — 허가된 계정/기록에 대해 사용
3. **Tenhou local preparation** — 사용 목적에 대한 권한 확인 후 사용

권장 방향은 synthetic-first입니다.

```text
strong Mortal checkpoint(s)
        ↓
population validation
        ↓
local self-play MJAI
        ↓
GRP + native learner
        ↓
Champion / learner / history cross-play
        ↓
duplicate evaluation + promotion
```

작은 human-log set이 확보되면 bootstrap/calibration에 사용하고 이후 self-play 비중을 높이는 방향을 권장합니다.

> [!WARNING]
> 현재 `RUN_SELFPLAY_POPULATION.bat generate ... activate`는 해당 mode의 Mortal + GRP dataset config를 `selfplay-population` root로 지정합니다. **Tenhou/Mahjong Soul + self-play를 원하는 비율로 자동 혼합하는 기능은 아직 구현되지 않았습니다.**

## Baseline behavior

Tenhou/Mahjong Soul preparation은 기존 mode-compatible `baseline.pth`가 있으면 보존하고 ABI 검사합니다.

없으면 validated unified smoke에서 생성된 checkpoint를 fixed canonical test-play reference로 사용할 수 있지만, 이것을 **강한 pretrained policy 또는 GRP 모델이라고 주장하지 않습니다.** GRP는 준비된 데이터로 mode별 학습/재사용합니다.

## Mahjong Soul

```text
Amae-Koromo metadata
   ↓
ranked UUID discovery
   ↓
authenticated record download
   ↓
raw protobuf
   ↓
pinned Majsoul → MJAI converter
   ↓
deterministic train/val
   ↓
GameplayLoader + GRP validation
```

Implemented tooling:

- 3P `pl3`, 4P `pl4` API family 분리
- 3P Sanma Throne → Jade → Gold
- 4P Throne → Jade → Gold
- discovery 최대 4 requests/s
- record-cap window recursive subdivision
- resumable cache/journal
- 3P north extraction → `nukidora`
- EN/KR Yostar OAuth compatibility layer
- secrets를 Git/TOML/experiment manifest/result에 영구 저장하지 않음
- downloaded records는 local runtime artifact

Pinned converter:

```text
NikkeTryHard/tenhou-to-mjai
69fb75a51c7efef3212be603227b2a58a9717237
```

Examples:

```powershell
.\RUN_MAJSOUL_FULL.bat prepare    5000 5000 authorized 10000 en
.\RUN_MAJSOUL_FULL.bat experiment 5000 5000 authorized 10000 en
.\RUN_MAJSOUL_FULL.bat full       5000 5000 authorized 10000 en
```

> [!CAUTION]
> wrapper 자체는 credential을 영구 저장하지 않지만 pinned child process의 인자 전달 특성상 token이 실행 중 로컬 process-inspection tool에 **일시적으로 보일 가능성**은 있습니다. 실제 credential 운영 시 상세 문서를 확인하십시오.

See: [`docs/MAJSOUL_TRAINING_PREP.md`](docs/MAJSOUL_TRAINING_PREP.md)

## Tenhou

| Purpose | Tool | Pin |
|---|---|---|
| Houou download/cache | `Apricot-S/houou-logs` | `d4ca693771517b67172521f2bd76517500db4a6e` |
| 3P XML → MJAI | `Mateces/tenhou-sanma-to-mjai` | `e0bd7bffe24227f97600c710cffa4490117b634a` |
| 4P XML → MJAI | `Jim137/mjlog2mjai` | `c133f7dbf61046feaf1af72369d9a44056807657` |

Examples:

```powershell
.\RUN_TENHOU_FULL.bat prepare    5000 5000 authorized 10000
.\RUN_TENHOU_FULL.bat experiment 5000 5000 authorized 10000
.\RUN_TENHOU_FULL.bat full       5000 5000 authorized 10000
```

The tooling provides:

- separate 3P/4P converter path
- deterministic 95/5 split
- GameplayLoader + GRP loader validation
- converter error-ratio gate
- mode-specific baseline + GRP
- local cache/resume
- no downloaded logs committed to Git

Historical archive availability is **not** treated as guaranteed. A large multi-year dataset is not silently promised by this workflow.

See: [`docs/TENHOU_TRAINING_PREP.md`](docs/TENHOU_TRAINING_PREP.md)

---

# Population self-play

Population self-play는 strong existing PTH를 초기 Champion/opponent로 삼고 Mortal/libriichi가 실제 MJAI game logs를 생성하는 synthetic bootstrap 경로입니다.

## Prepare checkpoints

### 3P

```powershell
.\RUN_SELFPLAY_POPULATION.bat prepare 3p "D:\models\sanma.pth"
```

3P는 native 1010 checkpoint와 Akagi legacy 775 checkpoint를 구분합니다.

### 4P

```powershell
.\RUN_SELFPLAY_POPULATION.bat prepare 4p `
  "D:\models\verified-4p.pth" `
  "D:\models\other-4p.pth"
```

첫 checkpoint는 preferred trusted Champion이지만 validation을 생략하지 않습니다.

Validation gates:

1. SHA-256 identify/deduplicate
2. mode / ABI detection
3. Mortal v4 strict load
4. forward smoke
5. actual `OneVsTwo` / `OneVsThree` gameplay smoke
6. pass한 모델만 active population으로 복사
7. reject reason을 manifest에 기록
8. ABI-compatible Champion만 해당 slot에 설치

```text
Mortal_Unified/runtime/3p/models/population/population.json
Mortal_Unified/runtime/4p/models/population/population.json
```

## Generate game logs

Small smoke first:

```powershell
.\RUN_SELFPLAY_POPULATION.bat generate 3p 24
.\RUN_SELFPLAY_POPULATION.bat generate 4p 32
```

Scale only after smoke:

```powershell
.\RUN_SELFPLAY_POPULATION.bat generate 3p 1000 activate
.\RUN_SELFPLAY_POPULATION.bat generate 4p 1000 activate
```

Behavior:

- resumable state cursor
- 3P: challenger 1 vs Champion 2 copies + seat rotation
- 4P: challenger 1 vs Champion 3 copies + seat rotation
- one member → mirror self-play
- 2+ members → bidirectional cross-play + Champion mirror
- generated MJAI player-count/header validation
- deterministic train/val assignment
- `GameplayLoader` + GRP validation before success
- interruption/retry reuse accounting
- mode-specific dataset activation

```text
Mortal_Unified/runtime/3p/data/selfplay-population/{train,val}/
Mortal_Unified/runtime/4p/data/selfplay-population/{train,val}/

Mortal_Unified/runtime/3p/runs/selfplay-data/state-3p.json
Mortal_Unified/runtime/4p/runs/selfplay-data/state-4p.json
```

See: [`docs/POPULATION_SELFPLAY.md`](docs/POPULATION_SELFPLAY.md)

---

# Evaluation backends

Evaluation infrastructure와 **Mortal native correctness path**를 구분합니다.

| Backend | Mode | Role | Windows | Status |
|---|---:|---|---:|---|
| `libriichi3p` / unified 3P arena | 3P | current reference / native correctness / population path | ✅ | ✅ |
| `libriichi` | 4P | correctness/reference fallback + native Mortal path | ✅ | ✅ |
| `mjx` | 4P | high-throughput batched evaluator | WSL2 / Linux container | ✅ backend registered |
| `mjx_sanma` | 3P | future high-throughput sanma evaluator | WSL2 / Linux | 🧪 experimental |
| legacy `mjai` | 4P | cross-check only | non-native | reference only |

`evaluation.select_backend(players=4, preference="auto")`는 4P에 MJX를 선택하도록 구성되어 있지만, 현재 repository의 native duplicate/model-comparison/population correctness 검증은 Mortal/libriichi 경로를 계속 사용합니다.

## MJX-Sanma parity policy

`mjx_sanma/manifest.toml`은 upstream을 다음에 pin합니다.

```text
mjx-project/mjx
ref:      v0.1.0
tree_sha: f52e27c4bfc6eb107af767e06266e2ba1e4c9333
production_backend = false
reference_backend  = libriichi3p
```

Production promotion 전 요구사항:

1. rule/tile-set patch
2. wall/deal
3. nuki protocol
4. state/scoring/game flow
5. legal actions/observation
6. Python bindings/parallel runner
7. `libriichi3p` parity
8. upstream file-hash match
9. required parity mismatch **zero**

따라서 **MJX-Sanma는 parity gate가 끝나기 전 production-disabled**입니다.

See: [`docs/EVALUATION_BACKENDS.md`](docs/EVALUATION_BACKENDS.md)

---

# Model comparison & promotion

새 checkpoint는 training loss만으로 Best가 되지 않습니다.

## Duplicate protocol

| Mode | Seat rotation per seed | Match |
|---|---:|---|
| 3P | A / B / C | Challenger 1 vs Champion 2 |
| 4P | A / B / C / D | Challenger 1 vs Champion 3 |

Comparison은 같은 seed range/key로 양방향 실행합니다.

```text
Candidate → Baseline
Baseline  → Candidate
```

Generated outputs:

```text
runtime/<mode>/runs/comparison/<name>/
├─ candidate-vs-baseline/
├─ baseline-vs-candidate/
├─ paired.jsonl
├─ paired.summary.json
├─ paired.summary.md
├─ native-stat.json
├─ native-stat.txt
├─ promotion-gate.json       # when rating profile is enabled
└─ comparison.json
```

Metrics include:

- placement distribution
- average rank
- tobi
- raw game-score delta
- rank point EV
- platform rating utility
- paired bootstrap confidence interval
- agari / houjuu / riichi / fuuro / ryukyoku rates
- native `libriichi.Stat` table

`--seed-count 100`은 quick preview입니다. 작은 strength 차이를 promotion할 때는 CI와 effect size가 안정될 만큼 sample을 확대해야 합니다.

### Seed key precision

Mortal duplicate seed key 예시 `0xD5DFAA4CEF265CD7`는 JavaScript safe integer 범위를 넘습니다. Control Center/Web API 경계에서는 **문자열로 유지**하여 rounding하지 않습니다.

See: [`docs/MODEL_COMPARISON.md`](docs/MODEL_COMPARISON.md)

---

# Rating-aware objectives

동일한 최종 순위/점수라도 platform/room/rank에 따라 실제 ladder value가 다릅니다. Rating context를 neural observation에 추가하지 않고 **training/evaluation utility**로만 사용합니다.

```text
public Mahjong observation ────────────> Mortal v4 Brain/DQN
                                               │
platform / room / rank / result ─> utility ────┘
```

이 방식은 Mortal/Akagi input ABI를 유지합니다.

## Implemented strategies

`training/rating_router.py`에 다음 전략이 구현되어 있습니다.

- **Universal** — mode별 configured mixture에서 objective sample
- **Specialized** — 하나의 target preset으로 학습/fine-tune
- **Curriculum** — universal에서 시작해 후반 target probability 증가

Preset/catalog:

```text
config/rating_presets.toml
config/rating_contexts.toml
training/rating.py
training/platform_rating.py
training/rating_router.py
```

Unknown context는 조용히 guessed fallback하지 않고 error로 처리합니다.

> 현재 Mortal observation에는 platform flag가 없으므로 **한 checkpoint가 inference 순간에 platform별 스타일을 자동 전환할 수 없습니다.** 실제 specialization은 별도 fine-tune/model selection/catalog로 처리하는 것이 ABI-safe합니다.

자동 model catalog와 장시간 platform-specific strength 측정은 후속 단계입니다.

See: [`docs/RATING_PRESETS_AND_DUAL_MODE.md`](docs/RATING_PRESETS_AND_DUAL_MODE.md)

---

# Akagi-NG API serving

Mortal-ROGS의 Akagi-NG 통합은 **API-only**입니다.

```text
untouched Akagi-NG
       │
       │ gzip HTTP + Authorization
       ▼
Mortal-ROGS inference API
       ├─ POST /react_batch_3p
       └─ POST /react_batch
       │
       ▼
mode-specific Mortal model slots
```

하지 않는 것:

- Mortal-ROGS PTH를 Akagi-NG `models`에 복사
- Akagi-NG 소스 수정/patch
- Akagi-NG가 Mortal-ROGS PTH 직접 `torch.load`
- Control Center가 Akagi 설치 경로를 요구

Historical `scripts/export_akagi_mortal.py`도 **의도적으로 deprecated/disabled**되어 direct-copy automation이 조용히 동작하지 않게 합니다.

## AkagiOT timing contract

Pinned Akagi reference 기준:

```text
connect timeout: 2 s
read timeout:    4 s
circuit breaker: 3 consecutive failures → open
recovery probe:  30 s
```

Mortal-ROGS server default deadline은 `3500 ms`로 Akagi의 4초 read timeout보다 먼저 실패시켜 client fallback/circuit-breaker가 정상 동작하도록 합니다.

## Serving reliability already implemented

- independent 3P/4P model slots
- strict load + warmup before publish
- background hot reload
- last-known-good fallback
- DEGRADED state on rejected replacement
- per-mode cross-request dynamic micro-batching
- malformed request isolation
- bounded queue / backpressure
- server-side deadline
- graceful drain / stop / restart
- Windows Ctrl+Break lifecycle handling
- serialized maintenance
- reload quiet/wait admission window
- shared-GPU forward coordination
- `max_device_executions=1` RTX production policy
- latency/queue/CUDA allocator telemetry
- benchmark + A/B sweep
- mixed-mode soak runner
- production profile transaction
- apply verification / rollback
- persisted profile recovery / drift reporting
- API key runtime-only handling

Management endpoints include:

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

Default production eligibility requires approximately:

```text
minimum duration      30 min
traffic               mixed 3P + 4P
concurrency           8
rows/request          1
p95 budget            100 ms
p99 budget            250 ms
peak VRAM             <= 92%
peak GPU temperature  <= 88 C
busy/deadline/errors  0
NVIDIA telemetry      required
```

CI runs the same report/gate logic as a short smoke but does **not** fabricate RTX 5080 production numbers.

See:

- [`docs/AKAGI_API_INTEGRATION.md`](docs/AKAGI_API_INTEGRATION.md)
- [`docs/INFERENCE_SERVING.md`](docs/INFERENCE_SERVING.md)
- [`docs/RTX5080_SERVING_SOAK.md`](docs/RTX5080_SERVING_SOAK.md)
- [`docs/INFERENCE_PRODUCTION_PROFILE.md`](docs/INFERENCE_PRODUCTION_PROFILE.md)
- [`docs/INFERENCE_PRODUCTION_RECOVERY.md`](docs/INFERENCE_PRODUCTION_RECOVERY.md)

---

# Control Center

Web UI는 기존 JobManager를 재사용하며 별도 experiment database/server/workflow framework를 만들지 않습니다.

현재 UI가 다루는 항목:

- unified runtime/bootstrap status
- 3P / 4P mode selection
- configuration
- GRP training
- offline Mortal / ROGS training
- existing self-play training flow
- TensorBoard
- checkpoint management
- evaluation / promotion
- Mortal / ROGS / ROGS+Global ablation
- bidirectional checkpoint comparison
- Akagi inference process lifecycle
- model reload
- serving metrics
- benchmark / A-B sweep
- soak
- production profile apply/rollback/recovery
- GPU utilization / VRAM / temperature / power
- jobs / logs / stop controls

### Currently not wired into the UI

새 **population checkpoint preparation + population self-play generation**은 현재 local validation 안정화를 위해 다음 entrypoint를 사용합니다.

```text
RUN_SELFPLAY_POPULATION.bat
```

이 기능은 검증 후 기존 JobManager/Control Center에 연결할 예정이며 새 service/DB를 추가하지 않습니다.

---

# Quick start

## Target environment

현재 주요 검증 환경:

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

다른 NVIDIA GPU도 사용할 수 있지만 training batch와 serving profile은 VRAM/성능에 맞춰 조정해야 합니다.

## 1. Clone

```powershell
cd C:\Users\<사용자명>\Downloads

git clone --branch research/mortal-rogs-v4-impl --single-branch `
  https://github.com/gkfyddl2662/JSGomoku.git `
  mortal-rogs

cd .\mortal-rogs
```

Update:

```powershell
cd C:\Users\<사용자명>\Downloads\mortal-rogs
git pull
```

## 2. Install + smoke unified runtime

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\setup_and_smoke_unified_windows.ps1"
```

Custom runtime path:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\setup_and_smoke_unified_windows.ps1" `
  -InstallRoot "D:\Mortal_Unified"
```

Managed setup covers, when required:

- pinned canonical Mortal checkout
- Python venv
- CUDA/PyTorch dependencies
- Rust/MSVC detection
- unified patch chain
- PyO3 `libriichi` build/install
- 3P/4P configs
- CUDA/BF16/compile smoke
- real gameplay/log/mini-training/evaluator/API/Control Center smoke

## 3. Re-run validation only

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\smoke_unified_windows.ps1" `
  -InstallRoot "C:\Users\<사용자명>\Downloads\Mortal_Unified"
```

## 4. Start Control Center

```powershell
C:\Users\<사용자명>\Downloads\Mortal_Unified\.venv\Scripts\python.exe -m app.main
```

```text
http://127.0.0.1:8188
```

---

# Local experiments

## Validate workstation

```powershell
.\RUN_LOCAL.bat validate
```

## Fair ablation

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

Existing-run policy:

```text
error   # default; refuse accidental reuse
fresh   # recreate only the isolated selected output
resume  # explicitly resume an existing run
```

## Full suite + production serving soak

```powershell
.\RUN_LOCAL.bat full fresh both
```

Results are outside both Git tree and unified source runtime:

```text
<workspace>\Mortal_ROGS_Results\YYYYMMDD-HHMMSS-*/
```

See: [`docs/LOCAL_WORKSTATION_RUN.md`](docs/LOCAL_WORKSTATION_RUN.md)

---

# Validation

## GitHub Actions

현재 branch는 8개 workflow contract를 유지합니다.

| Workflow | Coverage |
|---|---|
| `research-ci.yml` | ROGS / rating / evaluation research contracts |
| `unified-core-ci.yml` | patch/model/training contracts |
| `unified-runtime-ci.yml` | runtime/bootstrap/smoke contracts |
| `unified-gameplay-contract-ci.yml` | native gameplay/evaluator contracts |
| `libriichi-python-package-ci.yml` | PyO3 build/import + native E2E |
| `akagi-api-contract-ci.yml` | untouched AkagiOT HTTP contract |
| `akagi-3p-compat-ci.yml` | pinned 775 encoder/Bot/event-adapter contract |
| `windows-script-ci.yml` | Windows orchestration contracts |

Badge는 항상 branch 최신 commit 결과를 표시합니다. README에 정적 `HEAD` SHA나 오래된 `7/7`, `8/8` 문구를 박아 두지 않습니다.

## CI covers

- pinned source/patch contracts
- Rust compile/tests
- PyO3 package build/import
- 3P/4P model/engine ABI
- actual gameplay logs
- `GameplayLoader` roundtrip
- GRP/reward path
- real-log mini-training
- strict checkpoint save/reload
- 3P/4P evaluators
- duplicate → paired JSONL
- native Stat reports
- bidirectional model comparison
- rating/promotion contracts
- untouched AkagiOT client 3P/4P HTTP compatibility
- serving batching/backpressure/deadline/LKG/reload
- mixed-device coordination
- soak/profile/rollback/recovery logic
- pinned legacy 3P 775/Bot contract
- 4-slot sanma MJAI normalization
- hidden-information masking regression

## CI does not claim

- real RTX 5080 30-minute p95/p99/VRAM/temperature numbers
- long-training stability completion
- empirical ROGS > Mortal strength
- MJX-Sanma production parity completion
- full LuckyJ/Suphx reproduction

---

# Roadmap

## ✅ Implemented

- unified Mortal v4 3P/4P runtime
- one managed Python/Rust stack
- mode-isolated data/models/runs
- Windows RTX setup/smoke
- Control Center core lifecycle
- Mortal / ROGS / ROGS+Global hooks
- mode-aware GRP
- rating preset/utility/router foundation
- native 3P/4P gameplay and evaluator paths
- bidirectional duplicate comparison
- native strength/stat reporting
- promotion gate foundation
- AkagiOT API-only integration
- dynamic batching / LKG / hot reload / telemetry
- serving benchmark/soak/profile/rollback/recovery framework
- population checkpoint validation
- resumable population self-play generation
- Akagi legacy 775 3P teacher/opponent bridge
- legacy 4-slot MJAI normalization + hidden-info masking
- 4P MJX backend registration/reference integration
- MJX-Sanma pinned staged patch/parity framework

## 🚧 / 🧪 Current priorities

1. **4P population self-play local generation validation 확대**
2. **3P native 1010 learner bootstrap** from legacy-teacher MJAI
3. Champion + learner + historical snapshot population expansion
4. repeated cross-play → duplicate comparison → gated promotion
5. population self-play → existing Control Center JobManager wiring
6. real RTX 5080 30-minute mixed serving soak
7. long Mortal vs ROGS vs ROGS+Global experiments
8. small permitted Mahjong Soul / Tenhou bootstrap validation
9. statistically meaningful promotion sample scaling
10. platform-specific rating-aware fine-tuning measurement
11. MJX-Sanma legal-action/scoring/terminal parity completion

## 🗺️ Planned / only if measurements justify complexity

- configurable human-log + self-play dataset mixture
- automatic Universal → Specialized rating curriculum orchestration
- platform-specialized checkpoint catalog/model selection
- stronger population sampling and snapshot pruning
- controlled exploration scheduling
- Suphx-style privileged Oracle teacher
- sparse Search teacher distillation
- amortized pMCPA
- MJX-Sanma production enablement after zero-mismatch parity
- per-game runtime rating context only if an ABI-safe design is actually justified
- full LuckyJ-style neural CFR/search remains out of scope unless reproducible evidence/design warrants it

---

# Repository layout

```text
mortal-rogs/
├─ app/                         # Control Center backend, jobs, GPU, production controls
├─ static/                      # Control Center HTML/JS/CSS, experiments/inference/soak UI
├─ training/                    # game mode, ROGS, objective, rating utility/router
├─ evaluation/                  # backends, gating, paired results, strength/stat reports
├─ serving/                     # inference, coordination, resilience/lifecycle
├─ config/                      # ROGS, rating, ABI, backend, RTX presets
├─ mortal_unified/
│  └─ manifest.toml             # unified core source/mode contract metadata
├─ mjx_sanma/
│  └─ manifest.toml             # pinned MJX-Sanma parity/production policy
├─ scripts/                     # bootstrap, patches, data prep, eval, serving, self-play
├─ tests/                       # source/contract/regression tests
├─ docs/                        # detailed design and operations docs
├─ .github/workflows/           # 8 CI workflows
├─ RUN_LOCAL.bat                # validate / experiment / full
├─ RUN_MAJSOUL_FULL.bat         # Mahjong Soul prep + experiment/full handoff
├─ RUN_TENHOU_FULL.bat          # Tenhou prep + experiment/full handoff
├─ RUN_SELFPLAY_POPULATION.bat  # population prepare / generate
├─ start.ps1                    # local Control Center convenience entry
└─ README.md
```

---

# Documentation

| Document | Purpose |
|---|---|
| [`AKAGI_API_INTEGRATION.md`](docs/AKAGI_API_INTEGRATION.md) | untouched Akagi-NG API-only integration |
| [`INFERENCE_SERVING.md`](docs/INFERENCE_SERVING.md) | batching, deadline, reload, telemetry |
| [`INFERENCE_PRODUCTION_PROFILE.md`](docs/INFERENCE_PRODUCTION_PROFILE.md) | transactional production profile / rollback |
| [`INFERENCE_PRODUCTION_RECOVERY.md`](docs/INFERENCE_PRODUCTION_RECOVERY.md) | reboot recovery and drift reporting |
| [`RTX5080_SERVING_SOAK.md`](docs/RTX5080_SERVING_SOAK.md) | 30-minute RTX production gate |
| [`HYBRID_PARADIGM.md`](docs/HYBRID_PARADIGM.md) | ROGS / ACH / Suphx-inspired research design |
| [`RATING_PRESETS_AND_DUAL_MODE.md`](docs/RATING_PRESETS_AND_DUAL_MODE.md) | rating-aware 3P/4P objectives |
| [`MODEL_COMPARISON.md`](docs/MODEL_COMPARISON.md) | duplicate/bidirectional model comparison |
| [`POPULATION_SELFPLAY.md`](docs/POPULATION_SELFPLAY.md) | population validation and self-play bootstrap |
| [`MAJSOUL_TRAINING_PREP.md`](docs/MAJSOUL_TRAINING_PREP.md) | Mahjong Soul local preparation |
| [`TENHOU_TRAINING_PREP.md`](docs/TENHOU_TRAINING_PREP.md) | permission-aware Tenhou preparation |
| [`LOCAL_WORKSTATION_RUN.md`](docs/LOCAL_WORKSTATION_RUN.md) | one-command RTX workstation flow |
| [`EVALUATION_BACKENDS.md`](docs/EVALUATION_BACKENDS.md) | MJX/libriichi backend policy |

---

# Research / safety boundaries

## Compatibility

- Mortal v4 is the deployment baseline.
- 3P/4P checkpoints are physically separate.
- legacy 775 bridge does not replace native 1010 training ABI.
- Akagi-NG is a client; Mortal-ROGS owns/loading/serves checkpoints.

## Claims intentionally not made

- full LuckyJ training reproduction
- multiplayer Nash guarantee from ACH
- full Suphx Oracle/pMCPA implementation
- empirical ROGS superiority before long experiments
- short CI smoke as production benchmark
- MJX-Sanma production parity before gate completion

Terminology used intentionally:

```text
LuckyJ/ACH-inspired
Suphx-inspired
```

## Data / authorization

- external game logs are not bundled or redistributed by this repository
- use Mahjong Soul/Tenhou records only within permissions applicable to the intended use
- `authorized` arguments are explicit local acknowledgement, not a license grant
- credentials/tokens are not committed to Git

## Backups

Research branch users should separately back up valuable artifacts:

```text
Mortal_Unified/runtime/<mode>/models/
Mortal_Unified/runtime/<mode>/data/
Mortal_ROGS_Results/
```

Managed setup aims to preserve runtime artifacts but does not replace independent experiment/data backup practice.

---

# Legacy migration

Current recommended layout is `Mortal_Unified`. Older development layouts such as `Mortal_Sanma` and earlier `_runtime` structures are legacy paths.

`scripts/migrate_legacy_runtime.ps1` remains as compatibility/migration tooling. It is **not** the preferred fresh-install path.

Likewise direct Akagi PTH export is deprecated:

```text
scripts/export_akagi_mortal.py
```

The script intentionally exits with an actionable API-only message instead of silently copying a checkpoint into Akagi-NG.

---

# Troubleshooting

## `fatal: not a git repository`

```powershell
cd C:\Users\<사용자명>\Downloads\mortal-rogs
Test-Path .\.git
```

Expected: `True`.

## `ModuleNotFoundError: libriichi`

Use the unified runtime Python:

```powershell
C:\Users\<사용자명>\Downloads\Mortal_Unified\.venv\Scripts\python.exe `
  -c "import libriichi; print(libriichi.__file__)"
```

Managed PyO3 submodules use parent-module imports:

```python
from libriichi import consts
from libriichi import stat
from libriichi import arena
```

Do not rely on:

```python
from libriichi.arena import OneVsTwo
```

## `TritonMissing`

```powershell
git pull
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\smoke_unified_windows.ps1"
```

## MSVC / `link.exe`

Visual Studio 2022 Build Tools:

```text
Desktop development with C++
```

Managed setup/rebuild helper attempts to locate and initialize the MSVC environment automatically.

## CUDA OOM

Reduce training batch progressively, for example:

```text
512 → 384 → 256 → 128
```

Serving tuning should consider queue/deadline/micro-batch/VRAM telemetry together rather than only increasing batch size.

## Population self-play failure

Inspect:

```text
runtime/<mode>/models/population/population.json
runtime/<mode>/runs/selfplay-data/state-<mode>.json
runtime/<mode>/runs/selfplay-data/generation-*.json
```

For 3P, first distinguish **native 1010** from **legacy Akagi 775** ABI. Do not convert one feature layout into the other by padding weights.

---

<div align="center">

### Development branch

`research/mortal-rogs-v4-impl`

**Correctness first · Mortal v4 compatible · 3P and 4P always separate**

</div>
