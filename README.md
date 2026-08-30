# Mortal-ROGS Control Center

Windows에서 **3인마작(3P / Sanma)과 4인마작(4P / Yonma) AI를 하나의 프로그램으로 설치·학습·평가·관리**하기 위한 프로젝트입니다.

현재 기본 구조는 이미 단일 런타임으로 통합되어 있습니다.

```text
Mortal-ROGS
 ├─ Web UI                 ← 하나
 ├─ Mortal 코드            ← 하나
 ├─ Python 가상환경         ← 하나
 ├─ libriichi 확장          ← 하나
 │   ├─ 3P 모드
 │   └─ 4P 모드
 └─ runtime
     ├─ 3p
     │   ├─ data
     │   ├─ models
     │   └─ runs
     └─ 4p
         ├─ data
         ├─ models
         └─ runs
```

3P와 4P는 같은 프로그램과 같은 실행 환경을 사용하지만, **학습 데이터와 모델 파일은 서로 분리해서 관리**합니다.

> 현재는 연구/개발 버전입니다. Windows + RTX 5080 환경에서 3P/4P 통합 런타임, 실제 대국, 로그 재로딩, mini-training, checkpoint strict reload, evaluator까지 end-to-end 검증을 통과했습니다.

---

## 마일스톤

| 단계 | 목표 | 상태 |
|---|---|---|
| **Milestone 1** | 하나의 Web UI에서 3P / 4P 관리 | ✅ 완료 |
| **Milestone 2** | Windows + NVIDIA GPU 자동 설치 | ✅ 완료 |
| **Milestone 3** | 3P / 4P 단일 Mortal·Python·libriichi 런타임 | ✅ 완료 |
| **Milestone 4** | 실제 3P / 4P 대국·로그·학습·평가 E2E | ✅ 완료 |
| **Milestone 5** | 자동 평가 및 더 좋은 모델 자동 승격 | ✅ 기본 기능 완료 |
| **Milestone 6** | Akagi-NG 배포용 모델 최종 실전 검증 | 🚧 진행 중 |
| **Milestone 7** | MJX 기반 고속 평가 | 🚧 개발 중 |
| **Milestone 8** | 안정 버전 설치·업데이트·복구 UX 정리 | 🚧 진행 중 |

현재 우선순위는 **실제 장시간 학습 안정성, 배포 모델 검증, MJX 고속 평가**입니다.

---

# 주요 기능

## 3P / 4P 모드 선택

Web UI에서 다음 모드를 선택할 수 있습니다.

- **3P Sanma**
- **4P Yonma**

선택한 모드에 따라 데이터, 설정, 모델, 학습, 평가 경로가 자동으로 전환됩니다.

## AI 학습

- 준비된 대국 데이터로 Offline 학습
- GRP 학습
- Mortal-ROGS 학습
- Self-play 학습
- 학습 상태 저장 및 재시작
- TensorBoard 모니터링

## 모델 평가

- 3P: 1 vs 2 평가
- 4P: 1 vs 3 평가
- 통계 기반 후보 모델 비교
- 더 좋은 모델만 Best로 승격
- 배포 전 호환성 검사

## GPU 모니터링

Web UI에서 다음 정보를 확인할 수 있습니다.

- GPU 사용량
- VRAM 사용량
- GPU 온도
- 전력 사용량
- 현재 실행 중인 작업
- 학습 로그
- TensorBoard

---

# 지원 환경

현재 기본 설정과 실제 검증은 다음 환경을 기준으로 합니다.

- Windows 10 / 11 64-bit
- NVIDIA GPU
- RTX 5080 16GB 기준 preset 제공
- CUDA 12.8
- PyTorch 2.11
- BF16
- `torch.compile`
- Windows Triton 3.6.x

다른 NVIDIA GPU에서도 사용할 수 있습니다. VRAM이 부족하면 batch size를 낮추면 됩니다.

---

# 빠른 설치

## 1. 프로젝트 다운로드

PowerShell:

```powershell
cd C:\Users\<사용자명>\Downloads

git clone --branch research/mortal-rogs-v4-impl --single-branch `
  https://github.com/gkfyddl2662/JSGomoku.git `
  mortal-rogs

cd .\mortal-rogs
```

이미 받은 경우:

```powershell
cd C:\Users\<사용자명>\Downloads\mortal-rogs
git pull origin research/mortal-rogs-v4-impl
```

---

## 2. 단일 3P / 4P 런타임 설치

권장 설치 방법:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\setup_and_smoke_unified_windows.ps1"
```

기본 설치 위치는 프로젝트 폴더와 같은 상위 폴더의:

```text
Mortal_Unified
```

입니다.

원하는 위치를 직접 지정할 수도 있습니다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\setup_and_smoke_unified_windows.ps1" `
  -InstallRoot "D:\Mortal_Unified"
```

설치 스크립트는 필요한 경우 다음 작업을 자동으로 처리합니다.

- Rust toolchain 준비
- MSVC C++ Build Tools / Windows SDK 확인
- Python 가상환경 생성
- PyTorch 및 필요한 패키지 설치
- 단일 Mortal 소스 준비
- 3P / 4P 통합 patch 적용
- `libriichi` 빌드
- 3P / 4P 설정 생성
- CUDA / BF16 / `torch.compile` 검사
- 실제 대국·로그·mini-training·evaluator smoke test

이미 설치된 런타임을 다시 실행해도 `.venv`, 모델, 데이터, 실행 결과를 보존하면서 필요한 소스/확장만 갱신하도록 설계되어 있습니다.

---

# 설치 상태 확인

설치 후 전체 검증만 다시 실행하려면:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\smoke_unified_windows.ps1" `
  -InstallRoot "C:\Users\<사용자명>\Downloads\Mortal_Unified"
```

정상 완료 시 마지막에 다음이 표시됩니다.

```text
MORTAL_UNIFIED_RUNTIME_SMOKE_OK
MORTAL_UNIFIED_GAMEPLAY_E2E_OK
MORTAL_UNIFIED_REAL_DATA_TRAINING_E2E_OK
MORTAL_UNIFIED_TRAINED_CHECKPOINT_EVAL_E2E_OK
CONTROL_CENTER_UNIFIED_RUNTIME_OK
WINDOWS_UNIFIED_RUNTIME_SMOKE_OK
```

이 검사는 단순 import 테스트만 하는 것이 아니라 다음 흐름을 실제로 수행합니다.

```text
CUDA/BF16/torch.compile
        ↓
3P 3게임 + 4P 4게임
        ↓
*.json.gz 로그 생성
        ↓
GameplayLoader 재로딩
        ↓
실제 로그 mini-training
        ↓
checkpoint 저장 / strict reload
        ↓
3P 1 vs 2 / 4P 1 vs 3 evaluator
        ↓
Control Center unified routing 확인
```

---

# Web UI 실행

프로젝트 폴더에서:

```powershell
C:\Users\<사용자명>\Downloads\Mortal_Unified\.venv\Scripts\python.exe -m app.main
```

브라우저에서:

```text
http://127.0.0.1:8188
```

Web UI 상단에서 `3P Sanma` 또는 `4P Yonma`를 선택합니다.

프로젝트와 `Mortal_Unified`가 같은 상위 폴더에 있으면 Control Center가 unified runtime을 자동으로 감지합니다.

---

# 처음 사용한다면

권장 순서:

1. 프로젝트와 unified runtime 설치
2. Web UI 실행
3. 3P 또는 4P 선택
4. 학습 데이터 준비
5. Offline 학습 실행
6. TensorBoard로 상태 확인
7. 모델 평가
8. 기존 Best보다 좋아졌는지 확인
9. 조건을 통과하면 Best로 승격
10. 필요하면 Self-play로 추가 학습

처음에는 **Offline 학습 → 평가** 흐름부터 사용하는 것을 권장합니다.

---

# 3P Sanma

3P 모드 주요 기능:

- Sanma 학습 데이터 사용
- GRP 학습
- Mortal-ROGS 학습
- Self-play
- 1 vs 2 평가
- 모델 비교 및 승격

3P와 4P는 같은 Mortal/libriichi를 사용하지만 3P 모델은 별도 checkpoint로 저장됩니다.

---

# 4P Yonma

4P 모드 주요 기능:

- 4인마작 학습 데이터 사용
- GRP 학습
- Mortal-ROGS 학습
- Self-play
- 1 vs 3 평가
- 모델 비교 및 승격

4P 역시 3P와 독립된 checkpoint와 데이터 경로를 사용합니다.

---

# Mortal-ROGS란?

Mortal-ROGS는 기존 Mortal을 기반으로 **학습 과정과 모델 평가를 개선해 더 강한 AI를 만드는 것**을 목표로 합니다.

일반 사용자는 내부 학습 알고리즘의 세부 수식을 직접 조정할 필요가 없습니다.

주요 방향은 다음과 같습니다.

- 좋은 행동과 나쁜 행동의 차이를 더 잘 학습
- 한 국의 결과뿐 아니라 최종 순위까지 고려
- 보조 판단을 학습 단계에서 활용
- 여러 상대와 반복 self-play
- 실제 평가에서 좋아진 모델만 Best로 승격

배포용 모델 형식은 기존 Mortal v4 `Brain + current_dqn` 구조를 유지합니다.

---

# 모델 평가와 Best 승격

새 모델이 만들어져도 바로 기존 Best를 덮어쓰지 않습니다.

```text
새 모델
  ↓
여러 게임 평가
  ↓
기존 Best와 비교
  ↓
성능 개선 확인
  ↓
호환성 검사
  ↓
Best 승격
```

---

# MJX 고속 평가

MJX는 대량 게임을 빠르게 실행하기 위한 고속 평가 backend 후보입니다.

현재 상태:

- 4P: 고속 평가 backend로 개발/검증 중
- 3P: Sanma 규칙 이식 및 parity 검증이 아직 진행 중

따라서 현재 **정확성 기준 경로는 unified Mortal/libriichi evaluator**입니다.

MJX-Sanma가 기준 엔진과 충분히 일치하는 것이 확인되기 전에는 production 기본값으로 사용하지 않습니다.

---

# 기존 설치가 있는 경우

과거 개발 버전의 다음 경로는 legacy runtime으로 취급합니다.

```text
Mortal_Sanma
_runtime\3p
_runtime\4p
```

새 설치에서는 `Mortal_Unified`를 기본으로 사용합니다.

기존 데이터나 모델이 있다면 삭제할 필요는 없습니다. 필요한 파일을 mode별 unified storage로 옮길 수 있습니다.

```text
Mortal_Unified\runtime\3p\data
Mortal_Unified\runtime\3p\models
Mortal_Unified\runtime\4p\data
Mortal_Unified\runtime\4p\models
```

legacy bootstrap 스크립트는 당분간 호환/복구 목적으로 남겨두지만 **새 사용자에게 권장하는 기본 설치 경로는 아닙니다.**

---

# VRAM 부족 해결

학습 중 CUDA Out Of Memory가 발생하면 batch size를 낮춥니다.

```text
512 → 384 → 256 → 128
```

Web UI 설정에서 변경할 수 있습니다.

---

# 자주 발생하는 문제

## `fatal: not a git repository`

프로젝트 폴더로 이동합니다.

```powershell
cd C:\Users\<사용자명>\Downloads\mortal-rogs
```

확인:

```powershell
Test-Path .\.git
```

`True`가 나와야 합니다.

## `ModuleNotFoundError: libriichi`

unified runtime의 Python을 사용하고 있는지 확인합니다.

```powershell
C:\Users\<사용자명>\Downloads\Mortal_Unified\.venv\Scripts\python.exe `
  -c "import libriichi; print(libriichi.__file__)"
```

문제가 계속되면 unified setup script를 다시 실행하면 managed runtime이 필요한 부분을 복구합니다.

## `TritonMissing`

최신 unified setup/smoke는 Windows용 Triton을 자동으로 검사하고 필요한 버전을 설치합니다.

```powershell
git pull origin research/mortal-rogs-v4-impl

powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\smoke_unified_windows.ps1"
```

## MSVC / `link.exe` 오류

설치 스크립트가 MSVC 환경을 자동으로 검사합니다. 자동 설치가 불가능한 환경에서는 Visual Studio 2022 Build Tools의 다음 workload가 필요합니다.

```text
Desktop development with C++
```

---

# 현재 검증 범위

현재 자동 CI와 Windows 실기 검증은 다음을 포함합니다.

- 3P / 4P 단일 patch chain
- Rust compile / tests
- Python model / engine contract
- PyO3 `libriichi` 실제 빌드/import
- 3P / 4P 실제 대국
- 로그 생성 및 재로딩
- 실제 로그 mini-training
- checkpoint strict reload
- 3P / 4P evaluator
- Windows RTX 5080 CUDA/BF16/`torch.compile`
- Control Center unified routing

아직 주요 후속 과제로 남아 있는 것은 **장시간 실학습 안정성, 실제 배포 환경 검증, MJX 고속 평가**입니다.

---

# 개발 브랜치

현재 개발은 다음 브랜치에서 진행합니다.

```text
research/mortal-rogs-v4-impl
```

아직 연구/개발 단계이므로 중요한 모델과 학습 데이터는 별도 백업을 권장합니다.
