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
    assert cfg["mode"]["3p"]["obs_channels"] == 775
    assert cfg["mode"]["4p"]["obs_channels"] == 1012

    deployment = cfg["deployment"]
    assert deployment["modify_akagi_ng"] is False
    assert deployment["copy_checkpoint_to_akagi_ng"] is False
    assert deployment["akagi_loads_mortal_checkpoint"] is False
    assert deployment["mortal_rogs_owns_models"] is True

    model_backend = cfg["model_backend"]
    assert model_backend["require_mortal_v4_checkpoint"] is False
    assert model_backend["allow_non_mortal_backend"] is True
    assert model_backend["mortal_compat_version"] == 4


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
    coordination = (PROJECT_ROOT / "serving" / "coordination.py").read_text(encoding="utf-8")

    assert '@app.post("/react_batch")' in source
    assert '@app.post("/react_batch_3p")' in source
    assert '@app.get("/api/inference/health")' in source
    assert '@app.get("/api/inference/models")' in source
    assert '@app.get("/api/inference/metrics")' in source
    assert '@app.post("/api/inference/drain")' in source
    assert '@app.post("/api/inference/reload")' in source
    assert '@app.post("/api/inference/{mode}")' in source
    assert '"latency_ms"' in source
    assert '"abi_version": 4' in source
    assert '"mortal-rogs-inference-v1"' in source

    assert "AKAGI_READ_TIMEOUT_MS = 4000.0" in source
    assert 'default=float(os.getenv("MORTAL_INFERENCE_REQUEST_DEADLINE_MS", "3500"))' in source
    assert "run_in_threadpool(service.infer" in source
    assert "InferenceBusyError" in source
    assert "InferenceDrainingError" in source
    assert "DynamicBatcher" in serving
    assert "ModeTelemetry" in serving
    assert "DeviceExecutionCoordinator" in coordination
    assert "RequestLifecycle" in coordination
    assert '"policy": "fair-fifo"' in coordination
    assert "max_device_executions" in source
    assert "drain_timeout_ms" in source
    assert "signal.SIGBREAK" in source
    assert "server.should_exit = True" in source


def test_control_center_can_manage_reload_telemetry_and_scheduler_without_exposing_model_ownership_to_akagi() -> None:
    backend = (PROJECT_ROOT / "app" / "main.py").read_text(encoding="utf-8")
    jobs = (PROJECT_ROOT / "app" / "jobs.py").read_text(encoding="utf-8")
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

    assert "micro_batch_ms: float = Field(default=1.0" in backend
    assert "micro_batch_max_rows: int = Field(default=64" in backend
    assert "max_pending_requests: int = Field(default=128" in backend
    assert "request_deadline_ms: float = Field(default=3500.0, gt=0.0, lt=4000.0)" in backend
    assert "reload_poll_ms: float = Field(default=500.0" in backend
    for flag in (
        '"--micro-batch-ms"',
        '"--micro-batch-max-rows"',
        '"--max-pending-requests"',
        '"--request-deadline-ms"',
        '"--reload-poll-ms"',
    ):
        assert flag in backend
    for element_id in (
        "inferenceMicroBatchMs",
        "inferenceMaxRows",
        "inferenceMaxPending",
        "inferenceDeadlineMs",
        "inferenceReloadPollMs",
    ):
        assert element_id in ui
    assert "body.request_deadline_ms >= 4000" in ui
    assert "window.startInferenceApi = startInferenceApi" in ui

    assert 'job.kind == "inference_api"' in jobs
    assert "signal.CTRL_BREAK_EVENT" in jobs
    assert 'start_new_session=os.name != "nt"' in jobs
    assert "wait_timeout = 8.0 if graceful_inference else 5.0" in jobs

    assert "Shared Device" in ui
    assert "Lifecycle" in ui
    assert "contended_acquisitions_total" in ui
    assert "rejected_during_drain_total" in ui
    assert "peak_active_executions" in ui

    combined = "\n".join((backend, jobs, page, ui))
    assert "copy_checkpoint_to_akagi" not in combined
    assert "torch.load" not in ui
