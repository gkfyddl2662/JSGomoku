# Mortal Sanma Control Center

Windows + NVIDIA RTX 5080용 **Mortal 3인마작 학습/평가/self-play Web UI**입니다. `Lawrencelea/Mortal_Sanma`를 별도 폴더에 두고 원본 학습 파이프라인을 제어하므로, Web UI 코드와 Mortal 모델/데이터를 분리해서 관리할 수 있습니다.

## 제공 기능

- RTX 5080 / Blackwell 16GB VRAM 프리셋
- CUDA 12.8 PyTorch 설치를 포함한 Windows bootstrap
- Mortal 산마 학습 코드 성능 패치
  - CUDA + cuDNN benchmark
  - BF16 autocast
  - TF32 허용
  - `torch.compile`
  - pinned memory / persistent workers / prefetch
  - non-blocking host→GPU 전송
  - GRP float32 GPU 학습
- Web UI에서 GRP / Offline Mortal / 1vs2 / Self-play server+client+trainer 시작·중지
- 실시간 GPU/VRAM/온도/전력 상태
- 프로세스 로그 확인 및 강제 종료
- `config.sanma.toml` 읽기/편집/백업/RTX 5080 프리셋 적용
- Tenhou 三鳳南喰赤 추출과 `mjai-reviewer` JSONL 변환 실행
- 데이터/런 디렉터리 용량 확인
- `.pth` checkpoint 조회 및 `best_sanma.pth` 승격
- TensorBoard 실행 및 링크

## 1. 설치

PowerShell에서 이 저장소를 clone한 뒤:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\bootstrap.ps1 -InstallRoot C:\Mortal_Sanma
```

bootstrap은 다음을 수행합니다.

1. `Lawrencelea/Mortal_Sanma` clone
2. Web UI `.venv` 생성
3. CUDA 12.8 PyTorch 설치
4. `libriichi` maturin release build
5. `tenhou_dl` release build
6. RTX 5080 성능 패치 적용
7. `config.sanma.toml`에 5080 프리셋 merge

## 2. 실행

```powershell
cd <이 저장소 경로>
$env:MORTAL_SANMA_ROOT="C:\Mortal_Sanma"
.\.venv\Scripts\python.exe -m app.main
```

브라우저에서 `http://127.0.0.1:8188`을 엽니다.

기본 bind는 localhost 전용입니다. 외부 네트워크 공개가 필요할 때만 `MORTAL_WEBUI_HOST`를 변경하세요.

## RTX 5080 기본값

`config/rtx5080.sanma.toml`은 B40C192를 유지하면서 다음에서 시작합니다.

- Mortal batch: `512`
- AMP: `BF16`
- `torch.compile = true`
- cuDNN benchmark / TF32: enabled
- DataLoader workers: `8`
- prefetch factor: `4`
- GRP: CUDA, float32, batch `2048`
- 1v2: challenger/champion CUDA + AMP + compile

16GB VRAM에서 OOM이 나면 Web UI config 편집기에서 `control.batch_size`를 `384` → `256` 순으로 낮추세요. 여유 VRAM이 4GB 이상 지속되면 `640` 또는 `768`을 시험할 수 있습니다.

## 안전한 패치 방식

`scripts/patch_mortal.py`는 알려진 upstream 코드 anchor를 확인한 뒤 수정합니다. 원본은 최초 패치 시 `*.webui.bak`로 보존됩니다. upstream이 바뀌어 anchor가 사라지면 추측해서 수정하지 않고 오류로 중단합니다.

## 권장 학습 순서

1. Tenhou 산마 고단자 데이터 준비
2. Web UI → Data → 三鳳南喰赤 추출
3. Web UI → Data → MJAI JSONL 변환
4. GRP 학습
5. Offline Mortal 학습
6. 1 vs 2 대량 평가
7. 성능이 좋은 checkpoint를 Best로 승격
8. Self-play 시작
9. 다시 1 vs 2 평가

## 주의

- `torch.compile`이 특정 Windows/PyTorch 조합에서 문제가 생기면 `control.enable_compile=false`, `1v2.*.enable_compile=false`로 먼저 비활성화하세요.
- Mortal 모델 포맷과 observation/action space는 사용 중인 산마 fork와 맞아야 합니다.
- Web UI는 로컬 학습 orchestration 도구이며 Mahjong Soul/Tenhou 클라이언트 자동 조작 기능을 포함하지 않습니다.
