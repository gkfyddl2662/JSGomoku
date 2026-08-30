# Akagi-NG API 연동

Mortal-ROGS의 Akagi-NG 연동 방식은 **API 전용**입니다.

Akagi-NG의 `models` 폴더에 Mortal-ROGS가 학습한 `.pth` 파일을 복사하지 않습니다. 모델은 항상 `Mortal_Unified` 쪽에 남아 있고, Mortal-ROGS가 모델을 로드하여 HTTP 추론 API를 제공합니다.

## 구조

```text
Akagi-NG
  │
  │ gzip HTTP
  │ Authorization: <API key>
  ▼
Mortal-ROGS inference API
  ├─ POST /react_batch_3p   ← 3P
  └─ POST /react_batch      ← 4P
       │
       ▼
Mortal_Unified
  ├─ runtime/3p/models/best_mortal.pth
  └─ runtime/4p/models/best_mortal.pth
```

Akagi-NG는 모델 파일을 직접 열지 않습니다.

## Mortal-ROGS에서 API 시작

Control Center의 **SERVING → Akagi-NG · Mortal API**에서 다음을 설정합니다.

- Host: `127.0.0.1`
- Port: `8190`
- API Key: 예: `mortal-rogs-local`
- Device: `Auto (CUDA 우선)` 또는 `CUDA 0`

그 다음 **Akagi API 시작/재시작**을 누릅니다.

상태는 다음과 같이 표시됩니다.

- `OFFLINE`: API 서버가 실행되지 않음
- `RUNNING`: 3P/4P 모델이 정상적으로 현재 Best를 사용 중
- `DEGRADED`: 새 checkpoint hot-reload가 거부되어 이전 정상 모델로 계속 서비스 중

RTX 5080 CUDA 환경에서 mode별 상태에는 `cuda:0/compile/bfloat16`이 표시되는 것이 정상입니다.

## Akagi-NG 설정

Akagi-NG의 `settings.json`에서 `ot`를 다음과 같이 설정합니다.

```json
{
  "ot": {
    "online": true,
    "server": "http://127.0.0.1:8190",
    "api_key": "mortal-rogs-local"
  }
}
```

`api_key`는 Mortal-ROGS SERVING 패널에 입력한 값과 같아야 합니다.

Akagi-NG의 기존 AkagiOT client 계약을 그대로 사용합니다.

- 3P: `POST /react_batch_3p`
- 4P: `POST /react_batch`
- request body: gzip JSON `{"obs": ..., "masks": ...}`
- response: `actions`, `q_out`, `masks`, `is_greedy`

## 모델 승격과 hot reload

새 checkpoint가 생성되어도 API가 임의로 Best를 바꾸지 않습니다.

```text
candidate
  ↓
paired evaluation / rating gate
  ↓
Mortal v4 mode/action/observation ABI 검사
  ↓
API inference probe
  ↓
원자적 best_mortal.pth 승격
  ↓
API 자동 hot reload
```

3P와 4P Best는 별도 파일입니다.

```text
Mortal_Unified/runtime/3p/models/best_mortal.pth
Mortal_Unified/runtime/4p/models/best_mortal.pth
```

잘못된 mode의 checkpoint 또는 ABI가 맞지 않는 checkpoint가 Best 위치에 나타나면 API는 새 파일을 거부하고, 이미 로드되어 있던 마지막 정상 모델로 계속 응답합니다. 이 경우 `/health`와 Control Center에는 `DEGRADED`가 표시됩니다. 올바른 checkpoint가 다시 들어오면 자동으로 재로드되어 `RUNNING`으로 복구됩니다.

## 보안

기본 권장 설정은 로컬 PC 전용입니다.

```text
Host = 127.0.0.1
```

Mortal-ROGS API 서버는 loopback이 아닌 주소에 API key 없이 노출하는 것을 거부합니다.

외부 네트워크에 노출해야 하는 특별한 경우에는 강한 API key와 별도 네트워크 접근 제어를 함께 사용해야 합니다.

## 검증

전체 Windows smoke에는 Akagi API E2E가 포함됩니다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\smoke_unified_windows.ps1" `
  -InstallRoot "C:\Users\<사용자명>\Downloads\Mortal_Unified"
```

API 단계에서 검증하는 내용:

- pinned Akagi-NG AkagiOT HTTP 계약 호환
- gzip request
- Authorization API key
- 3P 44-action / 4P 46-action 응답
- 잘못된 mode shape 요청 거부
- 합법 action만 선택
- illegal Q의 JSON-safe 처리
- checkpoint hot-reload
- 잘못된 mode checkpoint 교체 거부
- 이전 정상 모델 fallback
- 올바른 checkpoint 복구 후 자동 reload
- CUDA 환경에서 BF16 + `torch.compile`

정상 완료 marker:

```text
MORTAL_AKAGI_API_PERFORMANCE_OK
MORTAL_AKAGI_API_HOT_RELOAD_OK
MORTAL_AKAGI_API_E2E_OK
```

## 중요한 원칙

Akagi-NG는 **UI/게임 연결/상태 추적/API client** 역할을 하고, Mortal-ROGS는 **모델 소유/학습/평가/승격/추론 serving**을 담당합니다.

따라서 Mortal-ROGS가 만든 모델 checkpoint를 Akagi-NG에 직접 배포하거나 Akagi-NG가 직접 로드하도록 만드는 것은 이 프로젝트의 기본 배포 경로가 아닙니다.
