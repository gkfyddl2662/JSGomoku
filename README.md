# Mortal-ROGS Control Center

Windows에서 **Mortal 3인마작(3P / Sanma)과 4인마작(4P / Yonma)을 하나의 프로젝트로 설치·학습·평가·관리**하기 위한 연구용 Control Center입니다.

이 프로젝트는 사용자에게는 하나의 프로그램처럼 보이지만, 내부적으로는 3P와 4P의 `libriichi` ABI가 서로 다르기 때문에 런타임만 안전하게 분리합니다.

- 3P `libriichi`: 44 actions
- 4P `libriichi`: 46 actions
- Web UI / 설정 / 평가 / ROGS 코드: 하나의 프로젝트에서 공통 관리
- 3P/4P 모델·데이터·실행 로그: 프로젝트 내부 `_runtime` 아래에서 모드별 관리

> 현재 브랜치는 Mortal-ROGS 연구/구현 브랜치입니다. 학습·평가 파이프라인은 계속 개발 중이며, 특히 MJX-Sanma와 3P Akagi-compatible Mortal v4 export는 아직 최종 검증 단계가 아닙니다.

---

## 1. 가장 빠른 설치 방법

### 필요한 환경

권장 환경:

- Windows 10/11 x64
- NVIDIA GPU — 기본 프리셋은 **RTX 5080 / Blackwell / 16GB VRAM** 기준
- 최신 NVIDIA Driver
- Git
- Python 3.11 권장
- Visual Studio 2022 Build Tools
  - `Desktop development with C++` 워크로드 권장
  - Rust `libriichi` 빌드에서 `link.exe`, `cl.exe`, Windows SDK 오류가 나면 필요합니다.

PowerShell에서 먼저 확인할 수 있습니다.

```powershell
git --version
python --version
nvidia-smi
```

Rust/Cargo는 아래 통합 bootstrap 명령에 `-InstallRustIfMissing`를 붙이면 `rustup`을 통해 자동 설치를 시도합니다.

### 저장소 Clone

```powershell
cd C:\Users\<사용자명>\Downloads

git clone --branch research/mortal-rogs-v4-impl --single-branch `
  https://github.com/gkfyddl2662/JSGomoku.git `
  mortal-rogs

cd .\mortal-rogs
```

현재 위치가 반드시 다음처럼 프로젝트 폴더 안이어야 합니다.

```text
PS C:\Users\<사용자명>\Downloads\mortal-rogs>
```

확인:

```powershell
Test-Path .\.git
git branch --show-current
Test-Path .\scripts\bootstrap_all_runtimes.ps1
```

정상 예시:

```text
True
research/mortal-rogs-v4-impl
True
```

### 3P + 4P 한 번에 설치

새 설치는 아래 **한 명령**을 권장합니다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\bootstrap_all_runtimes.ps1" `
  -InstallRustIfMissing
```

기본적으로 다음을 자동 수행합니다.

1. 프로젝트 내부 `_runtime\3p`에 Sanma Mortal clone
2. `_runtime\3p\.venv` 생성
3. 3P 전용 `libriichi` release build
4. 3P Tenhou 도구 build
5. RTX 5080 + Mortal-ROGS patch 적용
6. 3P config overlay 생성
7. 프로젝트 내부 `_runtime\4p`에 stock Mortal clone
8. `_runtime\4p\.venv` 생성
9. 4P 전용 `libriichi` release build
10. RTX 5080 + Mortal-ROGS patch 적용
11. 4P config overlay 생성
12. 3P/4P 통합 Windows smoke test 실행

정상적으로 끝나면 다음 계열의 메시지가 보입니다.

```text
MORTAL_RUNTIME_OK mode=3p
MORTAL_RUNTIME_OK mode=4p
UNIFIED_RUNTIME_BOOTSTRAP_OK
MORTAL_RUNTIME_SMOKE_OK
MORTAL_RUNTIME_SMOKE_OK
CONTROL_CENTER_DUAL_RUNTIME_OK
WINDOWS_DUAL_RUNTIME_SMOKE_OK
```

---

## 2. 설치 후 폴더 구조

기본 설치는 **프로젝트 하나만 관리하면 되도록** 구성됩니다.

```text
mortal-rogs\
│
├─ app\                    # FastAPI / Control Center
├─ config\                 # RTX / ROGS / rating 설정
├─ evaluation\             # 평가 / promotion gate
├─ training\               # Mortal-ROGS 학습 로직
├─ scripts\                # 설치 / 패치 / 검사 / export 도구
├─ static\                 # Web UI
├─ tests\
│
└─ _runtime\               # Git에서 제외되는 로컬 실행 환경
    │
    ├─ 3p\
    │   ├─ .venv\          # 3P libriichi — 44 actions
    │   ├─ Mortal\
    │   ├─ models\
    │   ├─ data\
    │   └─ runs\
    │
    └─ 4p\
        ├─ .venv\          # 4P libriichi — 46 actions
        ├─ mortal\
        ├─ models\
        ├─ data\
        └─ runs\
```

`_runtime/`은 `.gitignore`에 포함되어 있으므로 Mortal upstream 저장소, 모델, 데이터, venv가 메인 저장소에 실수로 commit되지 않습니다.

### 왜 `.venv`가 두 개인가?

3P와 4P 모두 Python 모듈 이름이 `libriichi`이지만 ABI가 다릅니다.

하나의 Python 환경에 둘을 같이 설치하면 마지막에 설치한 쪽이 다른 쪽을 덮어쓸 수 있습니다. 따라서 **프로젝트는 하나로 유지하되 Python runtime만 내부적으로 격리**합니다.

사용자는 보통 이 차이를 신경 쓸 필요가 없습니다. Web UI에서 3P / 4P 모드만 선택하면 해당 runtime으로 자동 라우팅됩니다.

---

## 3. Web UI 실행

프로젝트 루트에서:

```powershell
.\_runtime\3p\.venv\Scripts\python.exe -m app.main
```

브라우저에서:

```text
http://127.0.0.1:8188
```

기본 bind는 localhost 전용입니다.

Web UI에서 상단 **Game Mode**를 선택하면 해당 모드의 설정·데이터·학습·평가·체크포인트로 자동 전환됩니다.

- `3P Sanma`
- `4P Yonma`

TensorBoard 기본 포트:

- 3P: `6006`
- 4P: `6007`

---

## 4. Web UI에서 할 수 있는 작업

현재 Control Center에서 공통적으로 관리하는 주요 기능입니다.

- 3P / 4P runtime 상태 확인
- GPU / VRAM / 온도 / 전력 상태 확인
- RTX 5080 설정 preset 적용
- Mortal config 조회 및 편집
- GRP 학습
- Offline Mortal 학습
- 평가 실행
  - 3P: `one_vs_two.py`
  - 4P: `one_vs_three.py`
- Self-play server / client 실행
- TensorBoard 실행
- 데이터 / 모델 / run 디렉터리 상태 확인
- `.pth` checkpoint 조회
- 통계 기반 promotion gate
- Akagi ABI 호환성 검사
- MJX / MJX-Sanma 연구용 준비·패치·감사 도구

3P Lawrence 전용 Tenhou 다운로드/변환 도구는 3P 모드에서만 사용합니다. 4P는 stock Mortal 형식의 `*.json.gz` 데이터셋을 사용합니다.

---

## 5. 기존 `Mortal_Sanma` 설치가 이미 있는 경우

예전 방식으로 다음 위치에 3P를 이미 설치했다면:

```text
C:\Users\<사용자명>\Downloads\Mortal_Sanma
```

다시 처음부터 다운로드할 필요가 없습니다.

최신 코드를 받은 뒤:

```powershell
cd C:\Users\<사용자명>\Downloads\mortal-rogs
git pull
```

기존 3P를 프로젝트 내부로 이동하고 4P까지 설치:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\migrate_legacy_runtime.ps1" `
  -Legacy3PRoot "C:\Users\<사용자명>\Downloads\Mortal_Sanma" `
  -InstallRustIfMissing `
  -Bootstrap4P
```

마이그레이션 후:

```text
mortal-rogs\_runtime\3p
mortal-rogs\_runtime\4p
```

구조가 됩니다.

Windows virtualenv launcher는 절대 경로를 포함할 수 있기 때문에 기존 venv 자체를 억지로 이동하지 않고 `_runtime\3p\.venv`를 다시 생성합니다.

---

## 6. 수동 Smoke Test

bootstrap의 마지막에 기본적으로 실행되지만, 나중에 환경을 점검할 때 다시 실행할 수 있습니다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\smoke_windows.ps1"
```

이 테스트는 다음을 실제 Windows/GPU에서 확인합니다.

- 3P Python runtime 분리
- 4P Python runtime 분리
- 3P `ACTION_SPACE = 44`
- 4P `ACTION_SPACE = 46`
- Mortal observation ABI
- CUDA 사용 가능 여부
- BF16 지원
- BF16 CUDA matmul
- `torch.compile`
- 실제 Mortal `Brain + DQN` forward
- synthetic backward + AdamW optimizer step
- Web UI 3P / 4P API routing

정상 종료 기준:

```text
WINDOWS_DUAL_RUNTIME_SMOKE_OK
```

---

## 7. RTX 5080 기본 설정

프로젝트에는 모드별 RTX 5080 preset이 있습니다.

```text
config/rtx5080.sanma.toml
config/rtx5080.yonma.toml
```

기본 방향:

- CUDA 12.8 PyTorch
- BF16 AMP
- TF32 허용
- `torch.compile`
- cuDNN benchmark
- pinned memory
- persistent DataLoader workers
- prefetch
- non-blocking CPU → GPU transfer
- GRP GPU 학습

4P 기본 예시:

- batch size: `512`
- ResNet channels: `192`
- ResNet blocks: `40`
- DataLoader workers: `8`
- GRP batch: `2048`

### VRAM 부족 시

16GB VRAM에서 OOM이 발생하면 가장 먼저 `control.batch_size`를 낮춥니다.

권장 순서:

```text
512 → 384 → 256
```

반대로 VRAM 여유가 충분한 경우 더 큰 batch를 실험할 수 있지만, 속도와 품질을 실제 측정한 뒤 결정하는 것을 권장합니다.

---

## 8. 권장 사용 흐름

### 3P

1. 3P 데이터 준비
2. 필요한 경우 Tenhou Sanma 데이터 추출/변환
3. GRP 학습
4. Offline Mortal + ROGS 학습
5. 1 vs 2 평가
6. paired/statistical promotion gate
7. self-play / league 데이터 생성
8. 재학습
9. 재평가

### 4P

1. stock Mortal 호환 `*.json.gz` 데이터 준비
2. GRP 학습
3. Offline Mortal + ROGS 학습
4. 1 vs 3 평가
5. MJX 고속 평가 또는 libriichi correctness 평가
6. paired/statistical promotion gate
7. self-play / league 데이터 생성
8. 재학습
9. 재평가

---

## 9. Mortal-ROGS 개요

Mortal-ROGS는 배포 모델 자체를 복잡하게 만들기보다 **학습 teacher를 강화하고 최종 student는 Mortal-compatible 형태로 유지**하는 방향입니다.

ROGS는 현재 다음 구성요소를 중심으로 개발 중입니다.

- **R — Regret**
  - advantage/regret 기반 정책 개선
  - Hedge-like target
- **O — Oracle**
  - 학습 중에만 더 많은 정보를 사용하는 teacher
- **G — Global Reward / GRP**
  - 최종 순위·rating utility를 고려한 장기 보상
- **S — Search Distillation**
  - search/pMCPA 계열 teacher 결과를 Mortal student에 증류
- Offline Behavior Cloning
- Conservative Q-Learning regularization
- self-play league
- paired statistical evaluation

현재 loss는 value / regret / oracle / search / BC / CQL / entropy 항을 결합할 수 있도록 구현되어 있습니다.

---

## 10. Checkpoint / Akagi-NG 호환성

목표 배포 형식은 `Xe-Persistent/Akagi-NG`가 읽을 수 있는 Mortal checkpoint입니다.

목표 ABI:

- 3P: 44 actions
- 4P: 46 actions
- Mortal v4 deployment checkpoint
- `Brain + current_dqn`
- strict state-dict load

프로젝트에는 다음 단계의 promotion pipeline이 있습니다.

```text
후보 checkpoint
    ↓
paired statistical evaluation
    ↓
platform rating profile gate
    ↓
Akagi ABI validation
    ↓
atomic promotion
```

### 현재 중요한 제한

Lawrence Sanma upstream은 자체 v5 observation/model 경로를 가지고 있습니다. 현재 연구 runtime에서 3P 학습 자체는 가능하지만, **실제 3P 학습 결과가 최종 Akagi-NG용 Mortal v4 checkpoint로 완전히 export되는 경로는 아직 최종 smoke/parity 검증 전**입니다.

따라서 Akagi-NG production 배포 전에 반드시 프로젝트의 ABI checker와 실제 loader smoke test를 통과해야 합니다.

---

## 11. 평가 Backend

현재 기본 전략:

| 모드 | 목적 | Backend |
|---|---|---|
| 3P | reference / correctness | libriichi3p |
| 3P | 고속 평가 목표 | MJX-Sanma — 개발/검증 중 |
| 4P | correctness | libriichi |
| 4P | 고속 대량 평가 | MJX |

### MJX-Sanma 상태

MJX upstream은 원래 4P 중심 구조이므로 Sanma 지원을 단계적으로 patch하고 있습니다.

현재 연구 branch에는 rule/wall/protocol/state/scoring 관련 Sanma patch 단계가 들어가 있지만, production backend로 사용하려면 아직 다음이 필요합니다.

- Nuki 전체 state transition
- Sanma relative seat/wind 처리
- Nuki dora / rinshan semantics
- Python/env 3-player 지원
- deterministic paired parity
- libriichi3p와 score/action/result parity 검증

검증이 끝나기 전까지 `mjx_sanma`는 experimental backend로 취급합니다.

---

## 12. 프로젝트 업데이트

반드시 Git 저장소 루트에서 실행합니다.

```powershell
cd C:\Users\<사용자명>\Downloads\mortal-rogs
git pull
```

현재 폴더 확인:

```powershell
Test-Path .\.git
git status
git branch --show-current
```

`fatal: not a git repository`가 나오면 프로젝트 폴더가 아닌 위치에서 명령을 실행하고 있는 것입니다.

예:

```text
PS C:\Users\<사용자명>\Downloads>       # X
PS C:\Users\<사용자명>\Downloads\mortal-rogs> # O
```

---

## 13. 문제 해결

### `fatal: not a git repository`

현재 폴더에 `.git`이 없습니다.

```powershell
cd C:\Users\<사용자명>\Downloads\mortal-rogs
Test-Path .\.git
```

`True`가 나와야 합니다.

ZIP으로 받은 폴더라면 Git branch/update 기능을 사용할 수 없으므로 위의 clone 방법으로 다시 받는 것을 권장합니다.

### `cargo is required unless -SkipRustBuild is used`

실제 3P/4P ABI 테스트를 하려면 Rust build를 건너뛰면 안 됩니다.

통합 bootstrap을 다음처럼 실행합니다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\bootstrap_all_runtimes.ps1" `
  -InstallRustIfMissing
```

또는 수동 설치 후:

```powershell
cargo --version
rustc --version
```

을 확인합니다.

### `maturin failed: Couldn't find a virtualenv`

최신 bootstrap은 각 runtime의 `VIRTUAL_ENV`를 자동으로 설정합니다.

먼저 최신 코드를 받습니다.

```powershell
git pull
```

그 뒤 bootstrap을 다시 실행합니다.

### `link.exe`, `cl.exe`, Windows SDK, MSVC 오류

Visual Studio 2022 Build Tools에서 다음 workload를 설치합니다.

```text
Desktop development with C++
```

설치 후 새 PowerShell을 열고 bootstrap을 다시 실행합니다.

### `Wrong libriichi ABI`

3P와 4P Python 환경이 섞였다는 의미입니다.

정상 경로:

```text
_runtime\3p\.venv
_runtime\4p\.venv
```

직접 하나의 venv에 두 `libriichi`를 같이 설치하지 마세요.

### `torch.cuda.is_available() is false`

다음을 확인합니다.

```powershell
nvidia-smi
.\_runtime\3p\.venv\Scripts\python.exe -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
```

### `torch.compile` 오류

Windows / PyTorch / driver 조합에 따라 문제가 생길 수 있습니다.

우선 config에서 compile을 끄고 나머지 CUDA 경로가 정상인지 확인할 수 있습니다.

```text
control.enable_compile = false
```

평가 section의 challenger/champion compile 옵션도 필요 시 비활성화합니다.

### CUDA OOM

`control.batch_size`를 낮춥니다.

```text
512 → 384 → 256
```

GRP에서 OOM이면 `grp.control.batch_size`도 낮춥니다.

### bootstrap을 다시 실행해도 되는가?

가능합니다.

이미 runtime 폴더가 있으면 clone 단계는 재사용하고 필요한 dependency/build/patch/config 단계를 다시 수행합니다.

이미 RTX/ROGS patch가 적용된 legacy runtime을 통합 구조로 옮길 때는 `migrate_legacy_runtime.ps1`이 기존 patch를 감지해 보존합니다.

---

## 14. 고급 경로 Override

기본 runtime root는:

```text
<project>\_runtime
```

입니다.

필요하면 환경 변수로 변경할 수 있습니다.

```powershell
$env:MORTAL_RUNTIME_ROOT="D:\MortalRuntime"
```

모드별 override도 지원합니다.

```powershell
$env:MORTAL_3P_ROOT="D:\MortalRuntime\3p"
$env:MORTAL_4P_ROOT="D:\MortalRuntime\4p"
```

일반 사용자는 기본 `_runtime` 구조를 유지하는 것을 권장합니다.

---

## 15. CI / 개발 상태

Research CI는 다음을 자동 검사합니다.

- Python source compile
- core tests
- Mortal-ROGS tensor tests
- JavaScript syntax
- PowerShell syntax
- 3P upstream patch 적용/compile
- 4P upstream patch 적용/compile
- MJX-Sanma patch postconditions

단, GitHub Linux CI가 대신할 수 없는 항목이 있습니다.

- 실제 Windows path / PowerShell runtime
- RTX 5080 CUDA/BF16
- Windows `torch.compile`
- 실제 Windows-built `libriichi` ABI 격리

이 부분은 `scripts/smoke_windows.ps1`로 검증합니다.

---

## 16. 주요 스크립트

| 파일 | 용도 |
|---|---|
| `scripts/bootstrap_all_runtimes.ps1` | 새 PC에서 3P + 4P 통합 설치 |
| `scripts/bootstrap_runtime.ps1` | 특정 모드 runtime만 설치/복구 |
| `scripts/migrate_legacy_runtime.ps1` | 기존 외부 `Mortal_Sanma`를 `_runtime` 구조로 이전 |
| `scripts/smoke_windows.ps1` | 실제 Windows / CUDA / ABI 통합 테스트 |
| `scripts/smoke_runtime.py` | 모드별 CUDA/Mortal runtime probe |
| `scripts/patch_mortal_all.py` | 3P RTX + ROGS patch pipeline |
| `scripts/patch_mortal_4p.py` | 4P RTX + ROGS patch pipeline |
| `scripts/check_akagi_compat_dual.py` | 3P/4P Akagi ABI 검사 |
| `scripts/promote_if_passed.py` | 통계 + ABI gate를 통과한 checkpoint promotion |
| `scripts/patch_mjx_sanma.py` | MJX-Sanma 연구 patch pipeline |

---

## 17. 처음 설치하는 사용자용 요약

아래만 기억하면 됩니다.

```powershell
# 1. clone
cd C:\Users\<사용자명>\Downloads

git clone --branch research/mortal-rogs-v4-impl --single-branch `
  https://github.com/gkfyddl2662/JSGomoku.git `
  mortal-rogs

# 2. 프로젝트로 이동
cd .\mortal-rogs

# 3. 3P + 4P 설치 + smoke test
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\bootstrap_all_runtimes.ps1" `
  -InstallRustIfMissing

# 4. Web UI 실행
.\_runtime\3p\.venv\Scripts\python.exe -m app.main
```

브라우저:

```text
http://127.0.0.1:8188
```

이후에는 Web UI에서 **3P / 4P를 선택해서 사용하는 것이 기본 사용 방법**입니다.
