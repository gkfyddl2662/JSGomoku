# Mortal-ROGS Control Center

Windows에서 **3인마작(3P / Sanma)과 4인마작(4P / Yonma) AI를 하나의 프로그램으로 설치·학습·평가·관리**하기 위한 프로젝트입니다.

최종 목표는 3P용 프로그램과 4P용 프로그램을 따로 관리하는 것이 아니라, **하나의 Mortal 코어에서 모드만 3P / 4P로 바꾸어 사용하는 것**입니다.

> 현재는 개발 중인 연구 버전입니다. Web UI와 기본 학습·평가 기능은 통합되어 있지만, 내부 Mortal 엔진을 완전히 하나로 합치는 작업은 진행 중입니다.

---

## 마일스톤

| 단계 | 목표 | 상태 |
|---|---|---|
| **Milestone 1** | 하나의 Web UI에서 3P / 4P 관리 | ✅ 완료 |
| **Milestone 2** | Windows + NVIDIA GPU 자동 설치 환경 | ✅ 기본 기능 완료 |
| **Milestone 3** | 학습·평가·Self-play·TensorBoard 통합 관리 | ✅ 기본 기능 완료 |
| **Milestone 4** | **3P / 4P를 하나의 Mortal 코어로 통합** | 🚧 개발 중 |
| **Milestone 5** | 자동 평가 및 더 좋은 모델 자동 승격 | ✅ 기본 기능 완료 |
| **Milestone 6** | MJX를 이용한 고속 3P 평가 | 🚧 개발 중 |
| **Milestone 7** | 실제 3P / 4P 모델 배포 호환성 최종 검증 | 🚧 검증 중 |
| **Milestone 8** | 처음 사용하는 사람도 쉽게 설치·사용하는 안정 버전 | ⏳ 예정 |

### 현재 가장 중요한 작업

1. 3P와 4P가 같은 Mortal 코드와 같은 Python 환경을 사용하도록 통합
2. 3P 규칙을 통합 엔진에 이식
3. 3P / 4P 학습 결과가 기존 기준 엔진과 동일하게 동작하는지 검증
4. MJX 3인마작 평가 엔진 완성
5. 실제 학습 모델의 배포 테스트

---

# 이 프로젝트로 할 수 있는 것

## 3P / 4P 모드 선택

Web UI에서 원하는 게임 모드를 선택할 수 있습니다.

- **3P Sanma**
- **4P Yonma**

선택한 모드에 따라 데이터, 설정, 모델, 학습, 평가 화면이 자동으로 바뀝니다.

## AI 학습

- 준비된 대국 데이터로 학습
- GRP 학습
- Mortal-ROGS 학습
- Self-play 학습
- 학습 상태 저장 및 재시작

## 모델 평가

- 3P: 1 vs 2 평가
- 4P: 1 vs 3 평가
- 여러 게임 결과를 이용한 통계 평가
- 이전 Best 모델보다 실제로 좋아졌는지 자동 확인

## 모델 관리

- 학습된 `.pth` 모델 목록 확인
- 후보 모델 비교
- 조건을 통과한 모델만 Best 모델로 승격
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

## NVIDIA GPU 최적화

현재 기본 설정은 RTX 5080 / 16GB VRAM을 기준으로 맞추고 있습니다.

- CUDA
- BF16 학습
- 빠른 데이터 로딩
- `torch.compile`
- TensorFloat32
- GPU 메모리 전송 최적화

다른 NVIDIA GPU에서도 사용할 수 있으며, VRAM이 부족하면 batch size를 낮추면 됩니다.

---

# 현재 3P / 4P 통합 상태

사용자에게는 이미 하나의 Web UI로 보이지만, 현재 개발 버전 내부에는 안정성 확인을 위해 3P와 4P 실행 환경이 임시로 분리되어 있습니다.

```text
현재 개발 단계

Mortal-ROGS
 ├─ Web UI              ← 하나
 ├─ 학습/평가 관리       ← 하나
 ├─ 3P 임시 실행 환경
 └─ 4P 임시 실행 환경
```

최종 구조는 다음과 같이 바꾸는 것이 목표입니다.

```text
최종 목표

Mortal-ROGS
 ├─ Web UI              ← 하나
 ├─ Mortal 코어          ← 하나
 ├─ Python 환경          ← 하나
 ├─ Mahjong 엔진         ← 하나
 │    ├─ 3P 모드
 │    └─ 4P 모드
 └─ 모델/데이터
      ├─ 3P
      └─ 4P
```

3P와 4P는 게임 규칙과 모델 출력 크기가 다르기 때문에 **학습된 모델 파일은 각각 따로 유지**됩니다. 하지만 사용자가 프로그램을 두 개 관리할 필요는 없도록 만드는 것이 목표입니다.

현재 `Mortal_Sanma`는 3P 규칙이 올바르게 동작하는지 확인하기 위한 **참고 기준**으로 사용합니다. 최종 프로그램 자체를 `Mortal_Sanma`와 4P Mortal 두 개로 유지하는 것이 목표는 아닙니다.

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

PowerShell에서 확인:

```powershell
git --version
python --version
nvidia-smi
```

Rust는 설치 스크립트가 자동 설치를 시도할 수 있습니다.

---

## 2. 프로젝트 다운로드

```powershell
cd C:\Users\<사용자명>\Downloads

git clone --branch research/mortal-rogs-v4-impl --single-branch `
  https://github.com/gkfyddl2662/JSGomoku.git `
  mortal-rogs

cd .\mortal-rogs
```

정상적으로 받은 경우:

```powershell
Test-Path .\.git
Test-Path .\scripts\bootstrap_all_runtimes.ps1
```

두 명령 모두 `True`가 나와야 합니다.

---

## 3. 현재 개발 버전 설치

현재 개발 버전에서는 아래 명령이 3P와 4P 실행 환경을 자동으로 준비합니다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\bootstrap_all_runtimes.ps1" `
  -InstallRustIfMissing
```

자동으로 다음 작업을 수행합니다.

- 필요한 Python 환경 준비
- 3P / 4P 실행 환경 준비
- 필요한 마작 엔진 빌드
- PyTorch 설치
- GPU 최적화 설정 적용
- Mortal-ROGS 학습 기능 적용
- 설치 후 자동 테스트

> 단일 Mortal 코어 개발이 완료되면 이 설치 과정도 내부 실행 환경 하나만 만드는 방식으로 변경할 예정입니다.

---

# 실행 방법

프로젝트 폴더에서:

```powershell
.\_runtime\3p\.venv\Scripts\python.exe -m app.main
```

브라우저에서:

```text
http://127.0.0.1:8188
```

Web UI 상단에서 원하는 모드를 선택합니다.

```text
3P Sanma
4P Yonma
```

이후에는 대부분의 작업을 Web UI에서 할 수 있습니다.

---

# 처음 사용한다면

권장 순서:

1. 프로젝트 설치
2. Web UI 실행
3. 3P 또는 4P 선택
4. 학습 데이터 준비
5. Offline 학습 실행
6. TensorBoard로 상태 확인
7. 모델 평가
8. 더 좋은 모델인지 확인
9. 조건을 통과하면 Best 모델로 승격
10. 필요하면 Self-play로 추가 학습

처음에는 **Offline 학습 → 평가**까지만 사용하는 것을 권장합니다.

---

# 3P 사용

3P 모드에서 사용할 수 있는 주요 기능:

- Sanma 데이터 학습
- Tenhou 데이터 준비 도구
- GRP 학습
- Mortal-ROGS 학습
- 1 vs 2 평가
- Self-play
- 모델 비교 및 승격

3P 규칙의 기준 동작은 현재 `Mortal_Sanma`를 참고해 검증하고 있습니다.

---

# 4P 사용

4P 모드에서 사용할 수 있는 주요 기능:

- 4인마작 데이터 학습
- GRP 학습
- Mortal-ROGS 학습
- 1 vs 3 평가
- Self-play
- 모델 비교 및 승격

4P 학습 데이터는 Mortal에서 사용하는 `*.json.gz` 형식을 기준으로 합니다.

---

# Mortal-ROGS란?

Mortal-ROGS는 기존 Mortal을 기반으로 **학습 과정과 모델 평가 방법을 개선해 더 강한 AI를 만드는 것**을 목표로 합니다.

일반 사용자는 세부 알고리즘을 직접 조정할 필요가 없습니다.

주요 목표:

- 좋은 행동과 나쁜 행동의 차이를 더 잘 학습
- 한 국의 결과뿐 아니라 최종 순위까지 고려
- 강한 보조 판단을 학습에 활용
- 여러 상대와 반복해서 두면서 성능 개선
- 실제로 좋아진 모델만 Best로 교체

---

# 모델 평가와 Best 승격

새 모델이 만들어져도 바로 기존 Best 모델을 덮어쓰지 않습니다.

```text
새 모델
  ↓
여러 게임 평가
  ↓
기존 Best와 비교
  ↓
실제로 좋아졌는지 확인
  ↓
호환성 확인
  ↓
Best 모델로 승격
```

이 방식으로 일시적으로 운이 좋았던 모델이 바로 Best가 되는 것을 줄입니다.

---

# MJX 고속 평가

4P에서는 MJX를 고속 평가용으로 사용할 수 있습니다.

3P용 MJX는 현재 개발 중입니다.

현재 목표:

- 3인마작 규칙 지원
- 3P 게임 진행 지원
- 북빼기 등 3P 규칙 지원
- 기존 3P 기준 엔진과 결과 비교
- 검증 완료 후 대량 평가에 사용

현재 3P에서는 기존 3P 엔진을 기준으로 사용하며, **MJX-Sanma는 아직 실험 기능**입니다.

---

# 기존 `Mortal_Sanma` 설치가 있는 경우

기존에 다음과 같은 폴더를 만들었다면:

```text
C:\Users\<사용자명>\Downloads\Mortal_Sanma
```

다시 처음부터 받을 필요는 없습니다.

```powershell
cd C:\Users\<사용자명>\Downloads\mortal-rogs
git pull

powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\migrate_legacy_runtime.ps1" `
  -Legacy3PRoot "C:\Users\<사용자명>\Downloads\Mortal_Sanma" `
  -InstallRustIfMissing `
  -Bootstrap4P
```

이 경로는 **단일 코어가 완성되기 전 개발 버전용 마이그레이션 방법**입니다.

---

# 설치 상태 확인

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\smoke_windows.ps1"
```

현재 개발 버전에서 정상적으로 완료되면 마지막에:

```text
WINDOWS_DUAL_RUNTIME_SMOKE_OK
```

가 표시됩니다.

단일 코어 전환이 완료되면 이 검사 역시 하나의 실행 환경을 확인하는 방식으로 변경될 예정입니다.

---

# VRAM 부족 해결

학습 중 CUDA Out Of Memory 오류가 발생하면 batch size를 낮춥니다.

```text
512 → 384 → 256
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

## `cargo is required`

설치 명령에 다음 옵션을 사용합니다.

```text
-InstallRustIfMissing
```

## `maturin` virtualenv 오류

최신 코드를 받은 뒤 같은 설치 명령을 다시 실행합니다.

```powershell
git pull
```

## `link.exe`, `cl.exe`, Windows SDK 오류

Visual Studio 2022 Build Tools의 다음 항목이 필요합니다.

```text
Desktop development with C++
```

## CUDA를 찾지 못함

```powershell
nvidia-smi
```

에서 GPU가 정상적으로 표시되는지 확인합니다.

## `torch.compile` 오류

일부 Windows 환경에서는 `torch.compile`이 문제를 일으킬 수 있습니다. Web UI 설정에서 compile 옵션을 끈 뒤 다시 실행할 수 있습니다.

---

# 업데이트

프로젝트 폴더에서:

```powershell
git pull
```

일반적인 업데이트에서는 `_runtime`의 모델과 데이터가 삭제되지 않습니다.

---

# 현재 상태

- ✅ 하나의 Web UI에서 3P / 4P 선택
- ✅ 통합 학습·평가 관리 화면
- ✅ RTX 5080 기본 설정
- ✅ GRP / Mortal-ROGS 학습 기능
- ✅ Self-play 실행 기능
- ✅ TensorBoard
- ✅ 모델 관리 및 통계 평가
- 🚧 **3P / 4P 단일 Mortal 코어**
- 🚧 **3P / 4P 단일 Mahjong 엔진**
- 🚧 MJX-Sanma 고속 평가
- 🚧 실제 모델 배포 최종 검증
- ⏳ 안정 버전 설치/업데이트 경험 개선

---

# 한 줄 요약

**목표는 3P Mortal과 4P Mortal을 따로 쓰는 것이 아니라, Mortal-ROGS 하나에서 3P / 4P 모드만 바꿔 사용하는 것입니다.**

현재는 그 목표로 옮겨가는 개발 단계이며, 기존 이중 실행 환경은 검증이 끝날 때까지 임시 호환용으로 유지합니다.
