# Mortal-ROGS Control Center

Windows에서 **3인마작(3P / Sanma)과 4인마작(4P / Yonma) AI를 한 곳에서 설치·학습·평가·관리**하기 위한 프로젝트입니다.

복잡한 명령을 직접 입력하기보다, 한 번 환경을 만든 뒤 Web UI에서 모드를 선택해 사용하는 것을 목표로 합니다.

> 현재는 개발 중인 연구 버전입니다. 기본 학습/평가 환경은 사용할 수 있지만, 일부 고급 기능은 아직 완성 및 검증 중입니다.

---

## 마일스톤

| 단계 | 목표 | 상태 |
|---|---|---|
| **Milestone 1** | 3P / 4P를 하나의 프로젝트에서 관리 | ✅ 완료 |
| **Milestone 2** | Windows + RTX 5080용 자동 설치 및 실행 환경 | ✅ 완료 |
| **Milestone 3** | Web UI에서 학습·평가·Self-play·TensorBoard 관리 | ✅ 완료 |
| **Milestone 4** | 자동 평가 및 성능이 좋은 모델 승격 기능 | ✅ 기본 기능 완료 |
| **Milestone 5** | MJX를 이용한 고속 3P 평가 엔진 | 🚧 개발 중 |
| **Milestone 6** | 3P / 4P 모델의 실제 배포 호환성 최종 검증 | 🚧 검증 중 |
| **Milestone 7** | 설치·업데이트·학습·평가를 일반 사용자가 쉽게 쓰는 안정 버전 | ⏳ 예정 |

### 현재 가장 중요한 작업

- MJX 3인마작 규칙 및 게임 진행 완성
- 기존 3P 엔진과 MJX 결과가 동일한지 대량 비교
- 실제 학습된 3P / 4P 모델의 최종 배포 테스트
- 설치와 실행 과정을 더 간단하게 정리

---

## 주요 기능

### 3P / 4P 통합 관리

하나의 프로젝트에서 다음 두 모드를 모두 사용할 수 있습니다.

- **3P Sanma**
- **4P Yonma**

Web UI에서 모드만 선택하면 해당 모드의 설정, 데이터, 모델, 학습, 평가 화면으로 전환됩니다.

### AI 학습

- 기존 데이터로 학습
- GRP 학습
- Mortal-ROGS 학습
- Self-play 학습
- 3P / 4P 별도 학습 환경 자동 관리

### 평가

- 3P: 1 vs 2 평가
- 4P: 1 vs 3 평가
- 여러 게임 결과를 이용한 통계 평가
- 이전 모델보다 실제로 좋아졌는지 자동 판정

### 모델 관리

- 학습된 `.pth` 모델 목록 확인
- 후보 모델 평가
- 기준을 통과한 모델만 Best 모델로 승격
- 배포 전 호환성 검사

### 모니터링

Web UI에서 다음 정보를 확인할 수 있습니다.

- GPU 사용량
- VRAM 사용량
- GPU 온도
- 전력 사용량
- 실행 중인 작업
- 학습 로그
- TensorBoard

### RTX 5080 최적화 설정

기본 설정은 RTX 5080 / 16GB VRAM을 기준으로 준비되어 있습니다.

- BF16 학습
- CUDA 사용
- 빠른 데이터 로딩
- `torch.compile`
- TensorFloat32 사용
- GPU 메모리 전송 최적화

다른 NVIDIA GPU에서도 사용할 수 있지만, VRAM 용량에 따라 batch size 조정이 필요할 수 있습니다.

---

# 빠른 설치

## 1. 필요한 프로그램

권장 환경:

- Windows 10 / 11 64-bit
- NVIDIA GPU
- 최신 NVIDIA 드라이버
- Git
- Python 3.11 권장
- Visual Studio 2022 Build Tools

Visual Studio Build Tools 설치 시 다음 항목을 권장합니다.

```text
Desktop development with C++
```

PowerShell에서 기본 프로그램을 확인합니다.

```powershell
git --version
python --version
nvidia-smi
```

Rust는 설치 스크립트가 자동 설치를 시도할 수 있습니다.

---

## 2. 프로젝트 다운로드

PowerShell에서 원하는 폴더로 이동합니다.

예:

```powershell
cd C:\Users\<사용자명>\Downloads
```

프로젝트를 받습니다.

```powershell
git clone --branch research/mortal-rogs-v4-impl --single-branch `
  https://github.com/gkfyddl2662/JSGomoku.git `
  mortal-rogs
```

프로젝트 폴더로 이동합니다.

```powershell
cd .\mortal-rogs
```

정상적으로 받은 경우 다음 명령이 `True`를 출력합니다.

```powershell
Test-Path .\.git
Test-Path .\scripts\bootstrap_all_runtimes.ps1
```

---

## 3. 3P + 4P 한 번에 설치

처음 설치할 때는 아래 명령 하나를 권장합니다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\bootstrap_all_runtimes.ps1" `
  -InstallRustIfMissing
```

이 명령은 자동으로 다음 작업을 수행합니다.

- 3P 환경 설치
- 4P 환경 설치
- 필요한 Python 환경 생성
- 필요한 마작 엔진 빌드
- PyTorch / CUDA용 패키지 설치
- RTX 5080용 기본 설정 적용
- Mortal-ROGS 학습 기능 적용
- 설치가 정상인지 자동 테스트

설치 후 프로젝트 내부는 대략 다음과 같이 구성됩니다.

```text
mortal-rogs\
├─ app\
├─ config\
├─ evaluation\
├─ training\
├─ scripts\
├─ static\
│
└─ _runtime\
    ├─ 3p\
    │   ├─ .venv\
    │   ├─ models\
    │   ├─ data\
    │   └─ runs\
    │
    └─ 4p\
        ├─ .venv\
        ├─ models\
        ├─ data\
        └─ runs\
```

사용자는 일반적으로 `_runtime` 내부를 직접 수정할 필요가 없습니다.

---

# 실행 방법

프로젝트 폴더에서 다음 명령을 실행합니다.

```powershell
.\_runtime\3p\.venv\Scripts\python.exe -m app.main
```

브라우저에서 아래 주소를 엽니다.

```text
http://127.0.0.1:8188
```

Web UI 상단에서 원하는 모드를 선택합니다.

```text
3P Sanma
4P Yonma
```

선택한 모드에 따라 학습, 평가, 데이터, 모델 목록이 자동으로 전환됩니다.

---

# 처음 사용한다면

권장 순서는 다음과 같습니다.

1. 프로젝트 설치
2. Web UI 실행
3. 상단에서 3P 또는 4P 선택
4. 데이터 준비
5. GRP 또는 Offline 학습 실행
6. TensorBoard로 학습 상태 확인
7. 평가 실행
8. 성능이 좋아진 모델을 후보로 선택
9. 자동 평가 기준을 통과하면 Best 모델로 승격
10. 필요하면 Self-play로 추가 학습

처음에는 **Offline 학습 → 평가**까지만 익히는 것을 권장합니다.

---

# 3P 사용

3P 모드에서는 다음 기능을 사용할 수 있습니다.

- Sanma 데이터 학습
- Tenhou용 데이터 준비 도구
- GRP 학습
- Mortal-ROGS 학습
- 1 vs 2 평가
- Self-play
- 모델 비교 및 승격

3P 데이터 관련 도구는 Web UI의 3P 모드에서만 표시됩니다.

---

# 4P 사용

4P 모드에서는 다음 기능을 사용할 수 있습니다.

- 4인마작 데이터 학습
- GRP 학습
- Mortal-ROGS 학습
- 1 vs 3 평가
- Self-play
- 모델 비교 및 승격

4P 학습 데이터는 Mortal에서 사용하는 `*.json.gz` 형식을 기준으로 합니다.

---

# Mortal-ROGS란?

Mortal-ROGS는 기존 Mortal 모델을 기반으로 **학습 과정에서 더 다양한 정보와 평가 방법을 사용해 성능을 높이는 것**을 목표로 합니다.

일반 사용자가 세부 알고리즘을 설정할 필요는 없습니다. 기본 설정으로 학습하면 ROGS 기능이 학습 과정에 적용되도록 구성되어 있습니다.

핵심 목표는 다음과 같습니다.

- 단순 승패뿐 아니라 장기적인 결과까지 고려
- 좋은 행동과 나쁜 행동의 차이를 더 잘 학습
- 강한 보조 AI의 판단을 학습에 활용
- 여러 상대와 반복해서 두면서 성능 개선
- 새 모델이 실제로 좋아졌을 때만 Best 모델로 교체

---

# 모델 평가와 Best 승격

새로 학습된 모델이 있다고 해서 바로 기존 Best 모델을 덮어쓰지 않습니다.

기본 흐름은 다음과 같습니다.

```text
새 모델
  ↓
여러 게임 평가
  ↓
기존 Best 모델과 비교
  ↓
통계적으로 좋아졌는지 확인
  ↓
호환성 확인
  ↓
Best 모델로 승격
```

이 방식으로 학습 중 우연히 성적이 좋았던 모델이 바로 Best 모델이 되는 것을 줄입니다.

---

# MJX 고속 평가

4P에서는 MJX를 고속 평가용으로 사용할 수 있습니다.

3P용 MJX는 현재 개발 중입니다.

현재 목표:

- 3인마작 규칙 지원
- 3P 게임 진행 지원
- 3P 특수 규칙 지원
- 기존 3P 엔진과 동일한 결과가 나오는지 검증
- 검증 완료 후 대량 평가에 사용

따라서 **현재 3P의 기준 평가 엔진은 기존 3P 엔진이며, MJX-Sanma는 아직 실험 기능입니다.**

---

# 기존 `Mortal_Sanma` 설치가 있는 경우

예전 방식으로 이미 다음과 같은 폴더를 만들었다면:

```text
C:\Users\<사용자명>\Downloads\Mortal_Sanma
```

다시 처음부터 다운로드할 필요는 없습니다.

먼저 프로젝트를 최신 상태로 만듭니다.

```powershell
cd C:\Users\<사용자명>\Downloads\mortal-rogs
git pull
```

기존 3P 설치를 새 통합 구조로 옮기고 4P까지 설치합니다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\migrate_legacy_runtime.ps1" `
  -Legacy3PRoot "C:\Users\<사용자명>\Downloads\Mortal_Sanma" `
  -InstallRustIfMissing `
  -Bootstrap4P
```

완료되면 다음 구조로 통합됩니다.

```text
mortal-rogs\_runtime\3p
mortal-rogs\_runtime\4p
```

---

# 설치 상태 확인

환경이 정상인지 다시 확인하고 싶다면 다음 명령을 실행합니다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\smoke_windows.ps1"
```

정상적으로 완료되면 마지막에 다음 메시지가 표시됩니다.

```text
WINDOWS_DUAL_RUNTIME_SMOKE_OK
```

이 테스트는 실제 GPU 사용, 3P/4P 환경, 모델 실행, Web UI 연결 등을 확인합니다.

---

# VRAM 부족 해결

학습 중 CUDA Out Of Memory 오류가 발생하면 batch size를 낮춥니다.

기본값이 `512`인 경우 다음 순서로 낮춰보세요.

```text
512 → 384 → 256
```

Web UI의 설정 화면에서 변경할 수 있습니다.

RTX 5080보다 VRAM이 적은 GPU에서는 더 작은 값이 필요할 수 있습니다.

---

# 자주 발생하는 문제

## `fatal: not a git repository`

현재 PowerShell 위치가 프로젝트 폴더가 아닙니다.

```powershell
cd C:\Users\<사용자명>\Downloads\mortal-rogs
```

확인:

```powershell
Test-Path .\.git
```

`True`가 나와야 합니다.

---

## `cargo is required`

Rust가 설치되지 않은 상태입니다.

통합 설치 명령에 다음 옵션을 사용하면 자동 설치를 시도합니다.

```text
-InstallRustIfMissing
```

---

## `maturin`에서 virtualenv 오류

최신 프로젝트 코드를 받은 뒤 다시 설치합니다.

```powershell
git pull
```

그리고 이전에 사용한 bootstrap 명령을 다시 실행하면 됩니다.

---

## `link.exe`, `cl.exe`, Windows SDK 오류

Visual Studio 2022 Build Tools가 필요합니다.

설치할 때 다음 워크로드를 선택합니다.

```text
Desktop development with C++
```

---

## CUDA를 찾지 못함

다음을 확인합니다.

```powershell
nvidia-smi
```

정상적으로 GPU가 표시되는지 확인한 뒤 NVIDIA 드라이버를 업데이트합니다.

---

## `torch.compile` 오류

일부 Windows 환경에서는 `torch.compile`이 문제를 일으킬 수 있습니다.

Web UI 설정에서 compile 옵션을 끈 뒤 다시 실행할 수 있습니다.

---

# 업데이트

프로젝트를 업데이트할 때는 프로젝트 폴더에서:

```powershell
git pull
```

일반적인 업데이트에서는 `_runtime`의 모델과 데이터가 삭제되지 않습니다.

큰 런타임 변경이 있을 경우 README 또는 Release Note에 별도 안내할 예정입니다.

---

# 현재 상태

현재 사용할 수 있는 주요 기능:

- ✅ 3P / 4P 통합 프로젝트
- ✅ 통합 설치 스크립트
- ✅ RTX 5080 기본 설정
- ✅ Web UI
- ✅ 3P / 4P 학습 실행
- ✅ GRP 학습
- ✅ Self-play 실행
- ✅ TensorBoard
- ✅ 모델 목록 및 관리
- ✅ 통계 기반 모델 평가
- ✅ 안전한 Best 모델 승격 기본 기능
- 🚧 MJX-Sanma 고속 평가
- 🚧 실제 학습 모델의 최종 배포 호환성 검증
- ⏳ 안정 버전 설치/업데이트 경험 개선

---

# 한 줄 요약

처음 설치하는 사용자는 아래 순서만 기억하면 됩니다.

```powershell
# 1. Clone
git clone --branch research/mortal-rogs-v4-impl --single-branch `
  https://github.com/gkfyddl2662/JSGomoku.git mortal-rogs

# 2. 이동
cd .\mortal-rogs

# 3. 3P + 4P 설치
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

이후에는 Web UI에서 **3P / 4P 모드만 선택해서 사용**하면 됩니다.
