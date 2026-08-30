# Akagi-NG API 연동

Mortal-ROGS의 Akagi-NG 연동 방식은 **API 전용**입니다.

사용자는 Mortal-ROGS와 Akagi-NG를 서로 독립적으로 설치합니다. Mortal-ROGS는 별도로 다운로드한 **순정 Akagi-NG를 수정하거나 패치하지 않으며**, Akagi-NG 설치 폴더를 입력받지도 않습니다. 사용자는 Mortal-ROGS의 로컬 추론 API 주소와 API Key만 Akagi-NG의 기존 AkagiOT 설정에 입력하면 됩니다.

Akagi-NG의 `models` 폴더에 Mortal-ROGS가 학습한 `.pth` 파일을 복사하지 않습니다. 모델은 항상 `Mortal_Unified` 쪽에 남아 있고, Mortal-ROGS가 모델을 로드하여 HTTP 추론 API를 제공합니다.

## 구조

```text
별도 설치한 순정 Akagi-NG
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

Akagi-NG는 Mortal-ROGS의 모델 파일을 직접 열지 않습니다. Mortal-ROGS 역시 Akagi-NG의 설치 디렉터리나 모델 디렉터리에 파일을 쓰지 않습니다.

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

## 별도 설치한 Akagi-NG 설정

Akagi-NG는 공식/원본 배포본을 그대로 사용합니다. Mortal-ROGS 전용 파일을 Akagi-NG에 복사하거나 Akagi-NG 코드를 수정할 필요가 없습니다.

Akagi-NG의 `settings.json`에서 기존 `ot` 설정에 Mortal-ROGS 서버 주소와 API Key를 입력합니다.

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

Mortal-ROGS 서버는 Akagi-NG의 기존 AkagiOT client 계약을 그대로 구현합니다.

- 3P: `POST /react_batch_3p`
- 4P: `POST /react_batch`
- header: `Authorization: <API key>`
- request body: gzip JSON `{"obs": ..., "masks": ...}`
- response: `actions`, `q_out`, `masks`, `is_greedy`

따라서 Akagi-NG 입장에서는 Mortal-ROGS가 기존 AkagiOT 온라인 추론 서버처럼 보입니다.

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

전체 Windows smoke에는 Mortal-ROGS API E2E가 포함됩니다.

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

GitHub CI에서는 별도로 pinned 순정 Akagi-NG를 **read-only reference checkout**으로 가져옵니다. Akagi-NG 파일을 수정하지 않은 상태에서 그 저장소의 실제 `AkagiOTClient`와 `AkagiOTEngine`을 import하여 Mortal-ROGS API에 3P/4P 요청을 보내고, 테스트 후에도 Akagi-NG checkout이 clean인지 확인합니다.

정상 완료 marker:

```text
MORTAL_AKAGI_API_PERFORMANCE_OK
MORTAL_AKAGI_API_HOT_RELOAD_OK
MORTAL_AKAGI_API_E2E_OK
MORTAL_VANILLA_AKAGI_CLIENT_3P_OK
MORTAL_VANILLA_AKAGI_CLIENT_4P_OK
MORTAL_VANILLA_AKAGI_CLIENT_E2E_OK
```

## 중요한 원칙

Akagi-NG는 **UI/게임 연결/상태 추적/API client** 역할을 하고, Mortal-ROGS는 **모델 소유/학습/평가/승격/추론 serving**을 담당합니다.

따라서 다음은 하지 않습니다.

- Mortal-ROGS checkpoint를 Akagi-NG의 `models` 폴더로 복사
- Akagi-NG가 Mortal-ROGS checkpoint를 직접 `torch.load`
- Mortal-ROGS 설치 과정에서 Akagi-NG 소스 수정/패치
- Mortal-ROGS Control Center에서 Akagi-NG 설치 경로 요구

사용자에게 필요한 연결 정보는 **Mortal-ROGS API URL + API Key**뿐입니다.
