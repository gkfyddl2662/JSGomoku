from __future__ import annotations

import tomllib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_akagi_contract_is_api_only() -> None:
    with (PROJECT_ROOT / "config" / "akagi_abi.toml").open("rb") as f:
        cfg = tomllib.load(f)

    assert cfg["protocol"]["name"] == "akagiot-v1"
    assert cfg["mode"]["3p"]["endpoint"] == "/react_batch_3p"
    assert cfg["mode"]["4p"]["endpoint"] == "/react_batch"
    assert cfg["mode"]["3p"]["action_space"] == 44
    assert cfg["mode"]["4p"]["action_space"] == 46

    deployment = cfg["deployment"]
    assert deployment["modify_akagi_ng"] is False
    assert deployment["copy_checkpoint_to_akagi_ng"] is False
    assert deployment["akagi_loads_mortal_checkpoint"] is False
    assert deployment["mortal_rogs_owns_models"] is True


def test_control_center_does_not_require_an_akagi_install_path() -> None:
    source = (PROJECT_ROOT / "app" / "mortal.py").read_text(encoding="utf-8")
    assert "akagi_root" not in source
    assert '"--runtime-root"' in source


def test_direct_akagi_checkpoint_tools_are_retired() -> None:
    export_source = (PROJECT_ROOT / "scripts" / "export_akagi_mortal.py").read_text(encoding="utf-8")
    check_source = (PROJECT_ROOT / "scripts" / "check_akagi_compat.py").read_text(encoding="utf-8")
    dual_source = (PROJECT_ROOT / "scripts" / "check_akagi_compat_dual.py").read_text(encoding="utf-8")

    assert "Direct Mortal checkpoint export into Akagi-NG is disabled" in export_source
    assert "integration is API-only" in check_source
    assert "integration is API-only" in dual_source


def test_vanilla_akagi_client_smoke_is_read_only_and_resilient() -> None:
    source = (PROJECT_ROOT / "scripts" / "smoke_vanilla_akagi_client.py").read_text(encoding="utf-8")
    assert "AkagiOTClient" in source
    assert "AkagiOTEngine" in source
    assert "EngineProvider" in source
    assert "git_text(akagi_root, \"status\", \"--porcelain\")" in source
    assert "MORTAL_VANILLA_AKAGI_API_ONLY_IMPORT_OK" in source
    assert "MORTAL_VANILLA_AKAGI_PROVIDER_FALLBACK_OK" in source
    assert "MORTAL_VANILLA_AKAGI_CIRCUIT_RECOVERY_OK" in source
    assert "MORTAL_VANILLA_AKAGI_CLIENT_E2E_OK" in source
    assert '"libriichi" in sys.modules' in source


def test_managed_inference_api_preserves_akagiot_compatibility() -> None:
    source = (PROJECT_ROOT / "scripts" / "serve_akagi_api.py").read_text(encoding="utf-8")
    serving = (PROJECT_ROOT / "serving" / "resilient.py").read_text(encoding="utf-8")

    # Pinned AkagiOT compatibility endpoints remain unchanged.
    assert '@app.post("/react_batch")' in source
    assert '@app.post("/react_batch_3p")' in source

    # Mortal-ROGS owns the richer management/inference contract.
    assert '@app.get("/api/inference/health")' in source
    assert '@app.get("/api/inference/models")' in source
    assert '@app.get("/api/inference/metrics")' in source
    assert '@app.post("/api/inference/reload")' in source
    assert '@app.post("/api/inference/{mode}")' in source
    assert '"latency_ms"' in source
    assert '"abi_version": 4' in source
    assert '"mortal-rogs-inference-v1"' in source

    # Pinned Akagi has a 4s read timeout. Mortal-ROGS must fail fast before that,
    # rather than making Akagi wait for checkpoint compilation or a saturated queue.
    assert "AKAGI_READ_TIMEOUT_MS = 4000.0" in source
    assert 'default=float(os.getenv("MORTAL_INFERENCE_REQUEST_DEADLINE_MS", "3500"))' in source
    assert "run_in_threadpool(service.infer" in source
    assert "InferenceBusyError" in source
    assert "DynamicBatcher" in serving
    assert "ModeTelemetry" in serving
    assert "mortal-rogs-model-watcher-{mode}" in serving


def test_control_center_can_manage_reload_and_telemetry_without_exposing_model_ownership_to_akagi() -> None:
    backend = (PROJECT_ROOT / "app" / "main.py").read_text(encoding="utf-8")
    page = (PROJECT_ROOT / "static" / "index.html").read_text(encoding="utf-8")
    ui = (PROJECT_ROOT / "static" / "inference.js").read_text(encoding="utf-8")

    assert '@app.post("/api/inference/reload")' in backend
    assert '_inference_request("/api/inference/reload"' in backend
    assert "reloadInferenceModel(currentMode())" in page
    assert "reloadInferenceModel()" in page
    assert "async function reloadInferenceModel" in ui
    assert "'/api/inference/reload'" in ui
    assert "loadInferenceTelemetry" in ui
    assert "coalesced_requests_total" in ui
    assert "busy_rejections_total" in ui
    assert "timeouts_total" in ui

    combined = "\n".join((backend, page, ui))
    assert "copy_checkpoint_to_akagi" not in combined
    assert "torch.load" not in ui
