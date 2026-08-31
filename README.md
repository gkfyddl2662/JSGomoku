<div align="center">

# Mortal-ROGS

### Unified Mortal v4 Research · Training · Evaluation · Serving for 3P & 4P Riichi Mahjong

**Windows에서 3인마작(Sanma)과 4인마작(Yonma) Mortal AI를 하나의 런타임과 Control Center로 설치·학습·평가·운영하는 연구 플랫폼**

[![Research CI](https://github.com/gkfyddl2662/JSGomoku/actions/workflows/research-ci.yml/badge.svg?branch=research%2Fmortal-rogs-v4-impl)](https://github.com/gkfyddl2662/JSGomoku/actions/workflows/research-ci.yml)
[![Unified Runtime CI](https://github.com/gkfyddl2662/JSGomoku/actions/workflows/unified-runtime-ci.yml/badge.svg?branch=research%2Fmortal-rogs-v4-impl)](https://github.com/gkfyddl2662/JSGomoku/actions/workflows/unified-runtime-ci.yml)
[![Gameplay Contract](https://github.com/gkfyddl2662/JSGomoku/actions/workflows/unified-gameplay-contract-ci.yml/badge.svg?branch=research%2Fmortal-rogs-v4-impl)](https://github.com/gkfyddl2662/JSGomoku/actions/workflows/unified-gameplay-contract-ci.yml)
[![Akagi 3P Compatibility](https://github.com/gkfyddl2662/JSGomoku/actions/workflows/akagi-3p-compat-ci.yml/badge.svg?branch=research%2Fmortal-rogs-v4-impl)](https://github.com/gkfyddl2662/JSGomoku/actions/workflows/akagi-3p-compat-ci.yml)
[![Windows Script CI](https://github.com/gkfyddl2662/JSGomoku/actions/workflows/windows-script-ci.yml/badge.svg?branch=research%2Fmortal-rogs-v4-impl)](https://github.com/gkfyddl2662/JSGomoku/actions/workflows/windows-script-ci.yml)

**Mortal v4** · **Python 3.12** · **PyTorch 2.11 / CUDA 12.8** · **BF16** · **torch.compile** · **RTX 5080 target**

</div>

> [!IMPORTANT]
> 이 저장소는 현재 **연구/개발 브랜치**입니다. 핵심 Mortal 배포 ABI는 v4로 고정하고 있으며, 3P와 4P는 같은 코드/가상환경을 사용하되 **데이터·설정·체크포인트는 절대 섞지 않습니다.**

> [!NOTE]
> 기준 브랜치: `research/mortal-rogs-v4-impl`  
> Canonical Mortal pin: `0cff2b52982be5b1163aa9a62fb01f03ce91e0d2`  
> Akagi-NG compatibility pin: `11c0ffc0d70bf8142585b92405b4412976c9e205`

---

## 목차

- [프로젝트 한눈에 보기](#프로젝트-한눈에-보기)
- [현재 구현 상태](#현재-구현-상태)
- [아키텍처](#아키텍처)
- [3P / 4P ABI 계약](#3p--4p-abi-계약)
- [Mortal-ROGS 학습 패러다임](#mortal-rogs-학습-패러다임)
- [학습 데이터 준비](#학습-데이터-준비)
- [Population Self-play](#population-self-play)
- [평가 · 비교 · 승격](#평가--비교--승격)
- [Rating-aware 학습](#rating-aware-학습)
- [Akagi-NG API Serving](#akagi-ng-api-serving)
- [Control Center / Web UI](#control-center--web-ui)
- [빠른 시작](#빠른-시작)
- [로컬 실험 실행](#로컬-실험-실행)
- [검증 현황](#검증-현황)
- [로드맵](#로드맵)
- [프로젝트 구조](#프로젝트-구조)
- [상세 문서](#상세-문서)
- [연구 범위와 주의사항](#연구-범위와-주의사항)
- [문제 해결](#문제-해결)

---

# 프로젝트 한눈에 보기

Mortal-ROGS의 목표는 **Mortal v4 호환성을 유지하면서** 3P/4P 양쪽에서 더 좋은 학습 데이터, 보상, self-play, 평가, 승격, serving 파이프라인을 하나의 관리 환경으로 만드는 것입니다.

```text
                           Mortal-ROGS Control Center
                                      │
              ┌───────────────────────┼────────────────────────┐
              │                       │                        │
        Data / Training          Evaluation              Inference API
              │                       │                        │
      ┌───────┴────────┐      ┌───────┴────────┐      ┌────────┴────────┐
      │                │      │                │      │                 │
   3P Sanma          4P Yonma 1v2 / duplicate 1v3 / duplicate   AkagiOT HTTP
      │                │      │                │      │                 │
      └──────────┬─────┘      └────────┬───────┘      └────────┬────────┘
                 │                     │                       │
                 └──────────── Mortal_Unified ─────────────────┘
                                 │
                 one Mortal source / one .venv / one libriichi
                                 │
                  ┌──────────────┴──────────────┐
                  │                             │
           runtime/3p                    runtime/4p
      data / models / runs          data / models / runs
```

### 핵심 원칙

| 원칙 | 내용 |
|---|---|
| **Mortal v4 고정** | 배포 모델은 기존 `Brain + current_dqn` 구조를 유지합니다. |
| **3P/4P 완전 분리** | 하나의 프로젝트를 쓰지만 mode별 데이터와 checkpoint는 독립입니다. |
| **Teacher complexity, Student simplicity** | GRP/Oracle/Search/Regret 아이디어는 학습 측에 두고 배포 ABI는 늘리지 않습니다. |
| **실대국 기반 검증** | 단순 tensor forward가 아니라 실제 arena → MJAI → loader → train → evaluator 흐름을 검증합니다. |
| **승격은 평가 후에만** | 새 checkpoint가 생성됐다고 Best를 자동 덮어쓰지 않습니다. |
| **Akagi-NG는 API client** | Akagi-NG가 Mortal-ROGS `.pth`를 직접 로드하지 않습니다. |
| **Serving feature freeze** | serving은 기능 추가보다 correctness/reliability bug 수정이 우선입니다. |

---

# 현재 구현 상태

상태 표시는 다음 의미를 사용합니다.

- ✅ **완료** — 코드/계약이 구현되고 CI 또는 실제 smoke로 검증됨
- 🧪 **검증 중** — 기능은 구현됐지만 장시간·실데이터·성능 검증이 더 필요함
- 🚧 **진행 중** — 현재 연결/확장 작업 중
- 🗺️ **계획** — 설계 방향은 정했지만 production 구현으로 주장하지 않음

## 핵심 기능 매트릭스

| 영역 | 3P | 4P | 상태 / 비고 |
|---|---:|---:|---|
| 단일 Mortal/Python/libriichi runtime | ✅ | ✅ | 하나의 `Mortal_Unified` 사용 |
| Mode별 config/data/models/runs | ✅ | ✅ | 서로 독립 |
| Native Mortal v4 학습 ABI | ✅ | ✅ | 3P 1010ch / 4P 1012ch |
| 실제 arena gameplay | ✅ | ✅ | 3P `OneVsTwo`, 4P `OneVsThree` |
| MJAI 로그 → GameplayLoader roundtrip | ✅ | ✅ | native loader 검증 |
| GRP | ✅ | ✅ | mode-specific |
| Mortal baseline / ROGS / ROGS+Global ablation | ✅ | ✅ | Global reward 기본 OFF |
| Bidirectional duplicate comparison | ✅ | ✅ | seat rotation + paired seeds |
| Native `libriichi.Stat` 보고서 | ✅ | ✅ | agari/houjuu/riichi/fuuro 등 |
| Rating preset 평가 | ✅ | ✅ | mode별 preset/utility |
| Population checkpoint validation | ✅ | ✅ | actual evaluator smoke 포함 |
| Population self-play generator | ✅ | ✅ | CLI/BAT 구현 |
| Akagi legacy 775 teacher/opponent bridge | ✅ | — | 3P population/eval 전용 |
| AkagiOT HTTP API | ✅ | ✅ | `/react_batch_3p`, `/react_batch` |
| Dynamic batching / LKG / hot reload | ✅ | ✅ | shared GPU coordination 포함 |
| Serving benchmark / soak / profile / rollback | ✅ | ✅ | 30분 실 RTX gate는 별도 검증 필요 |
| Control Center 핵심 운영 기능 | ✅ | ✅ | training/eval/serving/experiments |
| Population self-play Web UI 연결 | 🚧 | 🚧 | 현재 `RUN_SELFPLAY_POPULATION.bat` 중심 |
| Tenhou + self-play 자동 혼합 curriculum | 🗺️ | 🗺️ | 현재 `activate`는 self-play dataset을 직접 지정 |
| MJX production evaluator | 🧪 | 🧪 | production 기준은 여전히 Mortal/libriichi |
| Full Suphx Oracle guiding | 🗺️ | 🗺️ | 아이디어/설계만, 완전 구현 주장 안 함 |
| Search teacher / amortized pMCPA | 🗺️ | 🗺️ | deployment ABI 유지 전제 |
| Full LuckyJ neural CFR/search 재현 | 🗺️ | 🗺️ | 재현을 주장하지 않음 |

## 지금까지 실제 로컬에서 확인된 추가 항목

- ✅ Windows + RTX 5080에서 3P/4P unified runtime, CUDA/BF16/`torch.compile`, gameplay, loader, mini-training, strict checkpoint reload, evaluator 검증
- ✅ 4P 실제 Mortal v4 checkpoint population 준비/Champion 설치 경로 검증
- ✅ Akagi legacy 3P `775 × 34 / 44 actions` checkpoint를 pinned `libriichi3p`로 실제 gameplay smoke 검증
- ✅ legacy 3P Champion을 native 1010 training slot과 분리하여 `akagi_legacy_champion.pth`로 설치
- ✅ legacy 3P teacher mirror self-play 24게임 생성, train/val 분할 및 loader/GRP validation 통과
- 🧪 4P population self-play의 별도 로컬 대량 생성/장시간 run은 계속 검증 중
- 🧪 실제 RTX 5080 **30분 production serving soak**은 아직 최종 실측 완료로 주장하지 않음
- 🧪 Mortal vs ROGS vs ROGS+Global의 장시간 strength 결과도 아직 실측 우위로 주장하지 않음

---

# 아키텍처

## Unified runtime

```text
workspace/
├─ mortal-rogs/                     # 이 저장소
├─ Mortal_Unified/                  # managed runtime
│  ├─ .venv/
│  ├─ mortal/                       # canonical Mortal + managed patches
│  ├─ libriichi/                    # unified native source
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

한 runtime 안에서 3P/4P를 지원하지만 다음은 **공유하지 않습니다.**

- train/validation data
- `current.pth`
- `best_mortal.pth`
- `baseline.pth`
- `grp.pth`
- experiment output
- population manifest
- promotion state

---

# 3P / 4P ABI 계약

## Native training ABI

| 항목 | 3P Sanma | 4P Yonma |
|---|---:|---:|
| Mortal model version | 4 | 4 |
| Players | 3 | 4 |
| Action space | 44 | 46 |
| Observation | `(1010, 34)` | `(1012, 34)` |
| Oracle observation | `(170, 34)` | `(217, 34)` |
| GRP input width | 6 | 7 |
| Evaluator | `OneVsTwo` | `OneVsThree` |
| Native checkpoint | 별도 | 별도 |

3P와 4P checkpoint를 tensor 단위로 합치거나 한 물리적 checkpoint에서 mode를 전환하지 않습니다.

## Akagi legacy 3P 775 ABI

Akagi-NG 계열의 기존 sanma checkpoint 중에는 native unified 1010ch와 다른 다음 ABI가 존재합니다.

```text
Observation: (775, 34)
Actions:     44
Mortal:      v4-compatible network/checkpoint family
Encoder:     pinned Akagi-NG libriichi3p
```

이 모델을 1010ch로 **padding/weight conversion하지 않습니다.** feature semantic이 다르기 때문입니다.

현재 bridge는 다음 구조를 사용합니다.

```text
Unified OneVsTwo arena
        │
        ├─ full internal MJAI
        │
        ▼
Akagi legacy event adapter
  ├─ 3-seat vector → historical 4-slot container
  ├─ opponents' initial hands masked with '?'
  └─ opponents' tsumo tile masked
        │
        ▼
pinned libriichi3p.mjai.Bot
        │
        ▼
775-channel observation / 44 actions
        │
        ▼
legacy Mortal v4 checkpoint
```

### 안전 규칙

- legacy 775 Champion은 `runtime/3p/models/akagi_legacy_champion.pth`에 설치합니다.
- native `current.pth`, `best_mortal.pth`, `baseline.pth`는 보존합니다.
- legacy 775 모델은 **현재 population teacher/opponent/evaluation bridge 용도**입니다.
- 현재 Akagi-facing managed serving의 native 3P Best ABI를 legacy 775로 조용히 바꾸지 않습니다.
- 775 teacher가 생성한 결과는 표준 MJAI game log이므로 native 1010 `GameplayLoader`의 학습 데이터로 사용할 수 있습니다.

---

# Mortal-ROGS 학습 패러다임

ROGS는 Mortal v4의 배포 구조를 깨지 않으면서 **regret/advantage 기반 self-play 안정화와 game-level reward**를 실험하기 위한 연구 경로입니다.

## 현재 구현된 학습 요소

- 기존 Mortal value/Q 학습 경로 유지
- CQL baseline behavior 유지
- ROGS centered advantage / regret-style objective
- Hedge-policy 기반 exploratory self-play hook
- BC/CQL anchoring
- online/offline curriculum hook
- 3P/4P mode-aware GRP
- 3P rank reward `[6, 0, -6]`
- 선택적 Global Reward shaping
- Global Reward 기본값 **OFF**
- `mortal`, `rogs`, `rogs-global` 공정 ablation
- 동일 seed/dataset/architecture/optimizer/budget 기준 비교
- 기본 training seed: `36887` (`0x9017`)

```text
train.py
  ↓
FileDatasetsIter
  ↓
GRP / RewardCalculator
  ↓
Mortal baseline or ROGS objective
  ↓
optimizer
  ↓
ordinary Mortal v4 checkpoint
```

## 논문 아이디어와 구현 범위

### LuckyJ / ACH-inspired

Actor-Critic Hedge의 sampled advantage/regret 및 Hedge policy 아이디어를 **multiplayer self-play optimization heuristic**으로 사용합니다.

> ACH의 이론적 Nash convergence 동기는 2-player zero-sum에 대한 것입니다. 3P/4P Mahjong에 그대로 적용되는 보장을 주장하지 않습니다.

### Suphx-inspired

현재 구현은 GRP 및 optional global reward shaping에 Suphx의 game-level reward 아이디어를 참고합니다.

다음은 아직 **완전 구현으로 주장하지 않습니다.**

- privileged Oracle teacher distillation
- runtime pMCPA
- search teacher distillation
- amortized pMCPA

### 배포 원칙

학습용 state에 optimizer, GRP, teacher, league metadata 등이 존재할 수 있어도 최종 배포 모델은 평범한 Mortal v4 형태를 유지합니다.

```text
config
mortal
current_dqn
```

Oracle/Search/GRP 전용 parameter를 `mortal`/`current_dqn`에 강제로 합치지 않습니다.

자세한 연구 설계: [`docs/HYBRID_PARADIGM.md`](docs/HYBRID_PARADIGM.md)

---

# 학습 데이터 준비

Mortal-ROGS는 **외부 패보가 없어도 population self-play로 시작할 수 있고**, 허가된 경우 Tenhou/Mahjong Soul 데이터를 bootstrap/calibration에 추가할 수 있습니다.

## 권장 synthetic-first 흐름

```text
강한 기존 Mortal checkpoint
          │
          ▼
population validation
          │
          ▼
local Mortal/libriichi self-play
          │
          ▼
MJAI train / val
          │
          ▼
GRP + native Mortal/ROGS learner
          │
          ▼
Champion ↔ Learner cross-play
          │
          ▼
duplicate evaluation / promotion
```

작은 human-log set이 있다면 초기 calibration에 사용하고, 이후 self-play 비중을 늘리는 방향을 권장합니다.

> [!WARNING]
> 현재 `generate ... activate`는 해당 mode의 Mortal + GRP dataset 설정을 `selfplay-population` 데이터로 가리킵니다. **Tenhou/Mahjong Soul + self-play를 비율로 자동 혼합하는 기능은 아직 구현되지 않았습니다.**

## Mahjong Soul

구현된 준비 흐름:

```text
Amae-Koromo metadata discovery
  → authenticated Mahjong Soul record download
  → raw protobuf
  → pinned converter
  → MJAI
  → deterministic train/val split
  → GameplayLoader + GRP validation
  → mode-specific GRP
```

주요 특성:

- 3P `pl3`, 4P `pl4` API family 분리
- 3P: Sanma Throne → Jade → Gold
- 4P: Throne → Jade → Gold
- API discovery 최대 4 req/s
- record-cap 도달 window 자동 subdivision
- resumable local cache/journal
- 3P `nukidora` 지원
- EN/KR Yostar OAuth compatibility layer
- password/token/packet을 Git/config/result에 영구 저장하지 않음
- 다운로드한 기록은 local runtime artifact이며 저장소에 포함하지 않음

Pinned converter:

```text
NikkeTryHard/tenhou-to-mjai
69fb75a51c7efef3212be603227b2a58a9717237
```

실행 예:

```powershell
.\RUN_MAJSOUL_FULL.bat prepare 5000 5000 authorized 10000 en
```

> 실제 계정/기록은 접근 권한이 있는 범위에서만 사용하십시오. EN/KR 인증 경로 tooling은 구현되어 있지만 실제 대량 데이터 수집 성공 여부는 외부 서비스 상태/인증 조건에도 영향을 받습니다.

상세: [`docs/MAJSOUL_TRAINING_PREP.md`](docs/MAJSOUL_TRAINING_PREP.md)

## Tenhou

Tenhou 경로는 허가된 local use를 전제로 pinned downloader/converter를 재사용합니다.

| 용도 | Tool | Pin |
|---|---|---|
| Houou download/cache | `Apricot-S/houou-logs` | `d4ca693771517b67172521f2bd76517500db4a6e` |
| 3P XML → MJAI | `Mateces/tenhou-sanma-to-mjai` | `e0bd7bffe24227f97600c710cffa4490117b634a` |
| 4P XML → MJAI | `Jim137/mjlog2mjai` | `c133f7dbf61046feaf1af72369d9a44056807657` |

```powershell
.\RUN_TENHOU_FULL.bat prepare 5000 5000 authorized 10000
```

- 3P/4P converter 분리
- deterministic 95/5 split
- GameplayLoader + GRP loader validation
- converter error ratio gate
- mode-specific baseline/GRP
- downloaded logs는 Git에 포함하지 않음

> 과거 연도 archive URL은 현재 신뢰할 수 있는 대규모 source로 간주하지 않습니다. 큰 historical dataset이 반드시 자동으로 확보된다고 주장하지 않습니다.

상세: [`docs/TENHOU_TRAINING_PREP.md`](docs/TENHOU_TRAINING_PREP.md)

---

# Population Self-play

외부 human log가 부족해도 기존 Mortal checkpoint를 teacher/opponent population으로 사용해 로컬에서 MJAI 패보를 생성할 수 있습니다.

## 1. Population 준비

### 3P

```powershell
.\RUN_SELFPLAY_POPULATION.bat prepare 3p "D:\models\sanma.pth"
```

native 1010 checkpoint와 Akagi legacy 775 checkpoint를 ABI에 맞게 구분하여 검증합니다.

### 4P

```powershell
.\RUN_SELFPLAY_POPULATION.bat prepare 4p `
  "D:\models\verified-4p.pth" `
  "D:\models\other-4p.pth"
```

첫 checkpoint는 preferred trusted Champion이지만 **검증을 생략하지 않습니다.**

검증 항목:

1. SHA-256 identify/deduplicate
2. mode/ABI 검사
3. strict Mortal v4 load
4. synthetic forward
5. actual `OneVsTwo` / `OneVsThree` gameplay smoke
6. 통과한 모델만 population directory에 복사
7. reject 이유를 manifest에 기록

Manifest:

```text
Mortal_Unified/runtime/3p/models/population/population.json
Mortal_Unified/runtime/4p/models/population/population.json
```

## 2. Self-play 패보 생성

작은 smoke부터 권장합니다.

```powershell
.\RUN_SELFPLAY_POPULATION.bat generate 3p 24
.\RUN_SELFPLAY_POPULATION.bat generate 4p 32
```

본 데이터 생성:

```powershell
.\RUN_SELFPLAY_POPULATION.bat generate 3p 1000 activate
.\RUN_SELFPLAY_POPULATION.bat generate 4p 1000 activate
```

특성:

- resumable state (`state-3p.json`, `state-4p.json`)
- 3P: 1 challenger vs 2 Champion copies, seat rotation
- 4P: 1 challenger vs 3 Champion copies, seat rotation
- 한 모델만 있으면 mirror self-play
- 여러 모델이면 양방향 cross-play 후 Champion mirror 포함
- generated MJAI header/player-count 검사
- deterministic train/val split
- real `GameplayLoader` + GRP validation 후 성공 처리
- interruption 후 같은 파일이 남아 있어도 reuse accounting

데이터:

```text
Mortal_Unified/runtime/3p/data/selfplay-population/{train,val}/
Mortal_Unified/runtime/4p/data/selfplay-population/{train,val}/
```

상세: [`docs/POPULATION_SELFPLAY.md`](docs/POPULATION_SELFPLAY.md)

---

# 평가 · 비교 · 승격

Mortal-ROGS는 training loss만으로 Champion을 교체하지 않습니다.

## Duplicate evaluation

동일 seed와 seat rotation을 사용합니다.

| Mode | 한 seed당 seat rotation | 기본 대결 |
|---|---:|---|
| 3P | A / B / C | Challenger 1 vs Champion 2 |
| 4P | A / B / C / D | Challenger 1 vs Champion 3 |

비교 runner는 양방향을 수행합니다.

```text
Candidate → Baseline
Baseline  → Candidate
```

같은 seed range/key를 사용해 role asymmetry를 줄입니다.

## 산출물

`runtime/<mode>/runs/comparison/<name>/` 아래에 다음이 생성됩니다.

- native duplicate logs
- `paired.jsonl`
- `paired.summary.json`
- `paired.summary.md`
- `native-stat.json`
- `native-stat.txt`
- optional `promotion-gate.json`
- `comparison.json`

## 지표

- placement distribution
- average rank
- tobi
- rank points
- game score delta
- platform rating utility
- paired bootstrap confidence interval
- win/agari rate
- deal-in/houjuu rate
- call/fuuro rate
- riichi rate
- ryukyoku rate

> `--seed-count 100`은 preview용입니다. 작은 모델 차이를 promotion할 때는 충분히 큰 duplicate sample과 안정적인 CI가 필요합니다.

상세: [`docs/MODEL_COMPARISON.md`](docs/MODEL_COMPARISON.md)

---

# Rating-aware 학습

플랫폼마다 같은 1위/2위/3위/4위 및 최종 점수의 ladder 가치가 다르므로 reward를 하나의 고정 placement vector로만 다루지 않습니다.

## 구현 방향

Rating context는 neural observation에 넣지 않습니다.

```text
public Mahjong observation ────────────> Mortal v4 Brain/DQN
                                               │
rank / score / platform preset ─> utility ─────┘  training/eval only
```

따라서 Akagi-compatible input ABI는 그대로 유지됩니다.

## 지원 전략

- **Universal** — 여러 rating objective를 mode별 mixture로 학습
- **Specialized** — 하나의 platform/room/rank preset에 fine-tune
- **Curriculum** — universal에서 시작해 target preset 비중을 점진 증가

`config/rating_presets.toml`과 rating utility layer가 mode별 설정을 관리합니다. Unknown context를 조용히 추측하지 않고 오류로 처리하도록 설계되어 있습니다.

중요한 제한:

> 현재 Mortal observation에는 platform flag가 없으므로 하나의 checkpoint가 inference 순간에 platform별 성향을 자동 전환할 수 없습니다. 실제 specialization은 **모델 선택/별도 fine-tune**으로 처리해야 합니다.

장시간 specialized/universal strength 측정과 자동 catalog 운영은 계속 진행할 작업입니다.

상세: [`docs/RATING_PRESETS_AND_DUAL_MODE.md`](docs/RATING_PRESETS_AND_DUAL_MODE.md)

---

# Akagi-NG API Serving

Akagi-NG 연동은 **API-only**가 기본 구조입니다.

```text
Vanilla Akagi-NG
      │
      │ gzip HTTP + Authorization
      ▼
Mortal-ROGS inference server
      │
      ├─ 3P POST /react_batch_3p
      └─ 4P POST /react_batch
      │
      ▼
Mortal_Unified mode-specific Best model
```

Mortal-ROGS는 다음을 하지 않습니다.

- Akagi-NG `models` 폴더에 checkpoint 복사
- Akagi-NG 소스 패치/수정
- Akagi-NG가 Mortal-ROGS checkpoint를 직접 `torch.load`
- Control Center에서 Akagi-NG 설치 경로 요구

사용자에게 필요한 연결 정보는 **API URL + API Key**입니다.

## Serving reliability

구현된 항목:

- mode별 persistent model slot
- strict checkpoint validation
- background hot reload
- warmup 후 atomic publish
- last-known-good fallback
- invalid replacement 시 DEGRADED + 기존 model 계속 serving
- per-mode cross-request dynamic micro-batching
- malformed request isolation
- bounded queue/backpressure
- server deadline (`3500 ms` default, pinned Akagi read timeout보다 짧음)
- graceful drain/stop/restart
- Windows Ctrl+Break handling
- serialized maintenance
- reload quiet-window admission
- 3P/4P shared GPU forward coordination
- RTX 5080 production profile `max_device_executions=1`
- CUDA allocator/latency/queue telemetry
- benchmark / A-B sweep
- serving soak
- production profile transaction
- verification / rollback / recovery
- API key runtime-only handling

## Management API

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

기본 production gate:

- 최소 30분
- mixed 3P + 4P
- concurrency 8
- p95 ≤ 100 ms
- p99 ≤ 250 ms
- busy/deadline/client error 없음
- degraded health 없음
- model signature 안정
- peak VRAM ≤ 92%
- GPU temperature ≤ 88°C
- `nvidia-smi` telemetry 필수

CI는 이 로직의 짧은 CPU smoke만 검증하며 **RTX 5080 성능 수치를 만들어내지 않습니다.** 실제 30분 RTX 측정은 별도 local gate입니다.

상세:

- [`docs/AKAGI_API_INTEGRATION.md`](docs/AKAGI_API_INTEGRATION.md)
- [`docs/INFERENCE_SERVING.md`](docs/INFERENCE_SERVING.md)
- [`docs/RTX5080_SERVING_SOAK.md`](docs/RTX5080_SERVING_SOAK.md)
- [`docs/INFERENCE_PRODUCTION_PROFILE.md`](docs/INFERENCE_PRODUCTION_PROFILE.md)
- [`docs/INFERENCE_PRODUCTION_RECOVERY.md`](docs/INFERENCE_PRODUCTION_RECOVERY.md)

---

# Control Center / Web UI

Control Center는 기존 하나의 JobManager/로그/stop workflow를 재사용합니다. 별도 experiment DB나 새 orchestration service를 만들지 않습니다.

현재 UI가 담당하는 영역:

- unified runtime bootstrap / 상태 확인
- 3P / 4P mode selection
- config editing
- GRP training
- Offline Mortal / ROGS training
- 기존 self-play training flow
- TensorBoard
- checkpoint 관리
- evaluation / promotion
- Akagi inference lifecycle
- model reload
- serving telemetry
- benchmark / soak / profile / rollback / recovery
- Mortal / ROGS / ROGS+Global ablation
- bidirectional model comparison
- GPU 사용률 / VRAM / 온도 / 전력 모니터링
- Job status / logs / stop

### 아직 UI에 연결 중인 것

새로운 **population bootstrap/self-play preparation**은 현재 안정화 우선으로 CLI/BAT 경로를 사용합니다.

```text
RUN_SELFPLAY_POPULATION.bat
```

로컬 3P/4P 검증이 충분히 끝난 뒤 기존 JobManager와 Control Center에 연결하는 것이 다음 단계입니다. 새로운 서버/DB를 추가하지 않습니다.

---

# 빠른 시작

## 요구 환경

현재 주 검증 환경:

- Windows 10 / 11 x64
- NVIDIA GPU
- RTX 5080 16GB target preset
- Python 3.12
- CUDA 12.8
- PyTorch 2.11
- BF16
- `torch.compile`
- Windows Triton 3.6.x
- Rust / MSVC Build Tools (setup에서 검사/준비)

다른 NVIDIA GPU에서도 사용할 수 있지만 batch/serving 설정은 VRAM과 성능에 맞게 조절해야 합니다.

## 1. Clone

```powershell
cd C:\Users\<사용자명>\Downloads

git clone --branch research/mortal-rogs-v4-impl --single-branch `
  https://github.com/gkfyddl2662/JSGomoku.git `
  mortal-rogs

cd .\mortal-rogs
```

업데이트:

```powershell
cd C:\Users\<사용자명>\Downloads\mortal-rogs
git pull
```

## 2. Unified runtime 설치 + smoke

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\setup_and_smoke_unified_windows.ps1"
```

기본 runtime:

```text
<workspace>\Mortal_Unified
```

직접 지정:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\setup_and_smoke_unified_windows.ps1" `
  -InstallRoot "D:\Mortal_Unified"
```

setup은 필요한 경우 다음을 수행합니다.

- canonical Mortal checkout/pin
- Python venv
- PyTorch/CUDA stack
- Rust/MSVC check
- managed patch chain
- PyO3 `libriichi` build/install
- 3P/4P config generation
- CUDA/BF16/compile smoke
- real gameplay/log/training/evaluator/API/Control Center smoke

## 3. 검증만 재실행

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\smoke_unified_windows.ps1" `
  -InstallRoot "C:\Users\<사용자명>\Downloads\Mortal_Unified"
```

## 4. Web UI

프로젝트 root에서:

```powershell
C:\Users\<사용자명>\Downloads\Mortal_Unified\.venv\Scripts\python.exe -m app.main
```

브라우저:

```text
http://127.0.0.1:8188
```

---

# 로컬 실험 실행

## Workstation validation

```powershell
.\RUN_LOCAL.bat validate
```

## 공정 ablation

양 mode 모두:

```powershell
.\RUN_LOCAL.bat experiment fresh both
```

단일 mode:

```powershell
.\RUN_LOCAL.bat experiment fresh 3p
.\RUN_LOCAL.bat experiment fresh 4p
```

Variant:

```text
mortal
rogs
rogs-global
```

기존 output 처리 정책:

```text
error   # 기본, 실수로 재사용/덮어쓰기 금지
fresh   # 해당 isolated run만 삭제 후 새로 시작
resume  # 명시적으로 이어서 학습
```

## Full suite + serving soak

```powershell
.\RUN_LOCAL.bat full fresh both
```

결과는 runtime 밖에 둡니다.

```text
<workspace>\Mortal_ROGS_Results\YYYYMMDD-HHMMSS-*/
```

상세: [`docs/LOCAL_WORKSTATION_RUN.md`](docs/LOCAL_WORKSTATION_RUN.md)

---

# 검증 현황

## GitHub Actions

현재 branch는 다음 8개 workflow 계약을 유지합니다.

| Workflow | 역할 |
|---|---|
| `research-ci.yml` | ROGS/research/training/eval contract |
| `unified-core-ci.yml` | core patch/model/training contract |
| `unified-runtime-ci.yml` | runtime/install/smoke contract |
| `unified-gameplay-contract-ci.yml` | native gameplay/evaluator contract |
| `libriichi-python-package-ci.yml` | PyO3 package/build/import contract |
| `akagi-api-contract-ci.yml` | vanilla AkagiOT HTTP API contract |
| `akagi-3p-compat-ci.yml` | pinned legacy 3P 775/Bot/event adapter contract |
| `windows-script-ci.yml` | Windows orchestration/script contract |

README 수정 직전 project HEAD에서는 8개 workflow가 모두 성공했습니다. README commit 이후에는 GitHub가 해당 commit 기준으로 다시 실행하는 결과를 badge에서 확인하십시오.

## CI가 실제로 확인하는 범위

- canonical patch chain
- Rust compile/tests
- PyO3 build/import
- 3P/4P model/engine contract
- real gameplay logs
- GameplayLoader roundtrip
- GRP/reward path
- mini-training
- strict checkpoint save/reload
- 3P/4P evaluator
- duplicate logs → paired JSONL
- native `libriichi.Stat`
- bidirectional model comparison
- rating/promotion gate contract
- vanilla AkagiOT 3P/4P HTTP client compatibility
- inference batching/backpressure/deadline/LKG/reload
- serving soak/profile/rollback/recovery logic
- pinned Akagi 3P 775 encoder/Bot contract
- Akagi 3P historical 4-slot MJAI container normalization
- hidden-information masking regression tests

## CI가 주장하지 않는 것

- 실제 RTX 5080 30분 performance 수치
- 장시간 training 안정성 완료
- ROGS가 Mortal보다 강하다는 실증 결과
- MJX 3P/4P production parity 완료
- full LuckyJ/Suphx reproduction

---

# 로드맵

## ✅ 완료

- unified Mortal v4 3P/4P runtime
- one `.venv` / one canonical Mortal / one managed libriichi
- mode-isolated data/models/runs
- Windows RTX setup/smoke
- Control Center 핵심 lifecycle
- Mortal/ROGS/ROGS+Global training hooks
- mode-aware GRP
- rating preset/utility foundation
- native 3P/4P gameplay + evaluators
- bidirectional duplicate comparison
- native statistics/reporting
- promotion gate foundation
- AkagiOT API-only integration
- inference hot reload/LKG/dynamic batching/telemetry
- serving soak/profile/rollback/recovery framework
- population checkpoint validation
- population self-play generator
- Akagi legacy 3P 775 population/eval bridge
- 3P legacy 4-slot MJAI compatibility + hidden-info masking

## 🚧 진행 중 / 다음 우선순위

1. **4P population self-play local generation 검증 확대**
2. **3P native 1010 learner bootstrap** — legacy 775 teacher가 만든 self-play 로그로 첫 native learner 학습
3. **3P/4P population 확장** — Champion + learner + historical snapshots
4. **cross-play → duplicate evaluation → gated promotion 반복**
5. **population self-play를 기존 Control Center JobManager에 연결**
6. **실제 RTX 5080 30분 mixed serving soak** 및 production profile 실측
7. **실제 Mortal vs ROGS vs ROGS+Global 장시간 ablation**
8. **Mahjong Soul / 허가된 Tenhou small bootstrap 실데이터 검증**
9. **statistically meaningful promotion sample 확대**
10. **platform-specific rating-aware fine-tuning 실측**

## 🗺️ 계획 / 실측 후 판단

- Tenhou/Mahjong Soul + self-play configurable mixture
- Universal → Specialized rating curriculum 자동화
- model catalog 기반 platform specialization selection
- stronger population sampling / historical snapshot pruning
- controlled exploration policy 개선
- Suphx-style privileged Oracle teacher
- sparse Search teacher distillation
- amortized pMCPA
- MJX parity gate 및 4P high-throughput backend production 여부 결정
- MJX-Sanma는 upstream/parity 조건이 충족되기 전 production-disabled 유지
- Universal per-game rating-context metadata는 Mortal ABI를 깨지 않는 방식이 실증적으로 필요할 때만 재검토

---

# 프로젝트 구조

```text
mortal-rogs/
├─ app/                         # Control Center backend / jobs / inference controls
├─ config/
│  ├─ hybrid_rogs_v4*.toml     # ROGS research config
│  ├─ rating_presets.toml       # platform rating presets
│  ├─ rating_contexts.toml
│  ├─ akagi_abi.toml
│  ├─ evaluation_backends.toml
│  ├─ rtx5080.sanma.toml
│  └─ rtx5080.yonma.toml
├─ docs/                        # 상세 설계/운영 문서
├─ scripts/                     # bootstrap, patch, data, eval, serving, self-play
├─ tests/                       # source/contract/regression tests
├─ .github/workflows/           # 8 CI workflows
├─ RUN_LOCAL.bat                # validate / experiment / full
├─ RUN_MAJSOUL_FULL.bat         # Mahjong Soul data + experiments
├─ RUN_TENHOU_FULL.bat          # Tenhou data + experiments
├─ RUN_SELFPLAY_POPULATION.bat  # population prepare / generate
└─ README.md
```

---

# 상세 문서

| 문서 | 내용 |
|---|---|
| [`AKAGI_API_INTEGRATION.md`](docs/AKAGI_API_INTEGRATION.md) | Vanilla Akagi-NG API-only 연동 |
| [`INFERENCE_SERVING.md`](docs/INFERENCE_SERVING.md) | batching, deadline, hot reload, telemetry |
| [`INFERENCE_PRODUCTION_PROFILE.md`](docs/INFERENCE_PRODUCTION_PROFILE.md) | production profile transaction/rollback |
| [`INFERENCE_PRODUCTION_RECOVERY.md`](docs/INFERENCE_PRODUCTION_RECOVERY.md) | reboot/recovery/drift handling |
| [`RTX5080_SERVING_SOAK.md`](docs/RTX5080_SERVING_SOAK.md) | 30분 production serving gate |
| [`HYBRID_PARADIGM.md`](docs/HYBRID_PARADIGM.md) | ROGS / ACH / Suphx-inspired 연구 설계 |
| [`RATING_PRESETS_AND_DUAL_MODE.md`](docs/RATING_PRESETS_AND_DUAL_MODE.md) | 3P/4P rating-aware reward/presets |
| [`MODEL_COMPARISON.md`](docs/MODEL_COMPARISON.md) | duplicate/bidirectional comparison |
| [`POPULATION_SELFPLAY.md`](docs/POPULATION_SELFPLAY.md) | checkpoint population + self-play bootstrap |
| [`MAJSOUL_TRAINING_PREP.md`](docs/MAJSOUL_TRAINING_PREP.md) | Mahjong Soul local preparation |
| [`TENHOU_TRAINING_PREP.md`](docs/TENHOU_TRAINING_PREP.md) | authorized Tenhou preparation |
| [`LOCAL_WORKSTATION_RUN.md`](docs/LOCAL_WORKSTATION_RUN.md) | RTX workstation one-command flow |
| [`EVALUATION_BACKENDS.md`](docs/EVALUATION_BACKENDS.md) | evaluator backend 방향과 MJX 범위 |

---

# 연구 범위와 주의사항

## Mortal / Akagi 호환성

- 배포는 Mortal v4가 기준입니다.
- 3P/4P checkpoint는 별도입니다.
- 3P 775 legacy compatibility는 teacher/opponent bridge이며 native 1010 training ABI를 대체하지 않습니다.
- Akagi-NG는 API client이며 Mortal-ROGS checkpoint 소유자는 Mortal-ROGS입니다.

## 연구 주장 범위

이 프로젝트는 다음을 **주장하지 않습니다.**

- LuckyJ 전체 학습법의 재현
- multiplayer Mahjong에 대한 ACH Nash-convergence 보장
- Suphx 전체 oracle/pMCPA 구현
- ROGS가 Mortal보다 이미 더 강하다는 실증적 결론
- short smoke를 production benchmark로 해석
- MJX-Sanma production parity 완료

현재 표현은 다음과 같이 사용합니다.

- **LuckyJ/ACH-inspired** regret/self-play ideas
- **Suphx-inspired** GRP/global reward ideas

## 데이터와 권한

- 외부 game log는 repository에 포함하지 않습니다.
- Mahjong Soul/Tenhou 데이터는 접근/사용 권한이 있는 경우에만 사용하십시오.
- credential/token은 Git에 저장하지 않습니다.
- Tenhou path의 `authorized` 인자는 사용 권한을 대신 부여하는 것이 아니라 명시적 local acknowledgement일 뿐입니다.

## 안정성

연구 브랜치이므로 중요한 다음 파일은 별도 백업을 권장합니다.

```text
runtime/<mode>/models/
runtime/<mode>/data/
Mortal_ROGS_Results/
```

managed setup은 runtime artifact 보존을 목표로 하지만, 장기 실험의 원본 모델/데이터 백업 책임까지 대체하지는 않습니다.

---

# 문제 해결

## `fatal: not a git repository`

```powershell
cd C:\Users\<사용자명>\Downloads\mortal-rogs
Test-Path .\.git
```

`True`여야 합니다.

## `ModuleNotFoundError: libriichi`

반드시 unified runtime Python을 확인합니다.

```powershell
C:\Users\<사용자명>\Downloads\Mortal_Unified\.venv\Scripts\python.exe `
  -c "import libriichi; print(libriichi.__file__)"
```

PyO3 submodule은 프로젝트 코드에서 다음 형태를 사용합니다.

```python
from libriichi import consts
from libriichi import stat
from libriichi import arena
```

`from libriichi.arena import ...` 같은 dotted import는 managed extension에서 사용하지 않습니다.

## `TritonMissing`

```powershell
git pull
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\smoke_unified_windows.ps1"
```

## MSVC / `link.exe`

Visual Studio 2022 Build Tools의 다음 workload가 필요합니다.

```text
Desktop development with C++
```

managed setup/rebuild helper가 가능한 범위에서 MSVC 환경을 자동으로 찾습니다.

## CUDA OOM

training batch를 단계적으로 낮추십시오.

```text
512 → 384 → 256 → 128
```

Serving은 batch size만 늘리는 것보다 queue/deadline/micro-batch/VRAM telemetry를 함께 확인해야 합니다.

## Population self-play 실패

우선 다음 파일을 확인합니다.

```text
runtime/<mode>/models/population/population.json
runtime/<mode>/runs/selfplay-data/state-<mode>.json
runtime/<mode>/runs/selfplay-data/generation-*.json
```

3P legacy checkpoint는 `obs=775/actions=44`인지, native 3P는 현재 unified ABI와 일치하는지 구분해야 합니다.

---

<div align="center">

### Development branch

`research/mortal-rogs-v4-impl`

**Correctness first · Mortal v4 compatible · 3P and 4P always separate**

</div>
