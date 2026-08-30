from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_soak_module():
    scripts = PROJECT_ROOT / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    path = scripts / "soak_inference_api.py"
    spec = importlib.util.spec_from_file_location("soak_inference_api", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_nvidia_smi_parser_and_production_preset() -> None:
    soak = load_soak_module()
    gpu = soak.parse_nvidia_smi_line("0, NVIDIA GeForce RTX 5080, 15000, 16384, 87, 71, 310.5")
    assert gpu["index"] == 0
    assert gpu["name"] == "NVIDIA GeForce RTX 5080"
    assert gpu["memory_used_mb"] == 15000.0
    assert 91.0 < gpu["memory_used_pct"] < 92.0

    settings = {
        "micro_batch_ms": 1.0,
        "micro_batch_max_rows": 64,
        "max_pending_requests": 128,
        "request_deadline_ms": 3500.0,
        "reload_poll_ms": 500.0,
        "max_device_executions": 1,
        "reload_quiet_ms": 150.0,
        "reload_wait_ms": 1000.0,
        "drain_timeout_ms": 3500.0,
    }
    results = {
        "3p": {"latency_ms": {"p99": 80.0}},
        "4p": {"latency_ms": {"p99": 90.0}},
    }
    samples = [{"modes": {"3p": {"peak_queue_depth": 2}, "4p": {"peak_queue_depth": 3}}}]
    preset = soak.derive_production_preset(settings, results, samples, concurrency=8)
    assert preset["max_device_executions"] == 1
    assert preset["max_pending_requests"] >= 128
    assert 1000.0 <= preset["request_deadline_ms"] < 4000.0
    assert preset["reload_quiet_ms"] >= 150.0
    assert preset["reload_wait_ms"] >= 1000.0


def test_production_gate_requires_duration_latency_stability_and_optional_gpu() -> None:
    soak = load_soak_module()
    results = {
        "3p": {"failed_requests": 0, "latency_ms": {"p95": 50.0, "p99": 80.0}},
        "4p": {"failed_requests": 0, "latency_ms": {"p95": 60.0, "p99": 90.0}},
    }
    deltas = {
        "3p": {"busy_rejections_total": 0, "timeouts_total": 0},
        "4p": {"busy_rejections_total": 0, "timeouts_total": 0},
    }
    device = {"peak_active_executions": 1, "max_parallel_executions": 1}
    samples = [{"degraded": False}]
    gpu = {"available": True, "peak_memory_used_pct": 85.0, "peak_temperature_c": 70.0}
    gate = soak.evaluate_production_gate(
        results,
        deltas,
        device,
        gpu,
        samples,
        elapsed_s=1800.0,
        min_duration_s=1800.0,
        latency_budget_ms=100.0,
        p99_budget_ms=250.0,
        vram_ceiling_pct=92.0,
        temperature_ceiling_c=88.0,
        require_gpu_telemetry=True,
        model_signature_changed=False,
        reload_failures=0,
    )
    assert gate["passed"] is True
    assert gate["validation_level"] == "production"

    short = soak.evaluate_production_gate(
        results,
        deltas,
        device,
        {"available": False},
        samples,
        elapsed_s=2.0,
        min_duration_s=1800.0,
        latency_budget_ms=100.0,
        p99_budget_ms=250.0,
        vram_ceiling_pct=92.0,
        temperature_ceiling_c=88.0,
        require_gpu_telemetry=False,
        model_signature_changed=False,
        reload_failures=0,
    )
    assert short["passed"] is False
    assert short["validation_level"] == "smoke"


def test_control_center_exposes_soak_without_putting_api_key_in_process_args() -> None:
    router = (PROJECT_ROOT / "app" / "inference_benchmark.py").read_text(encoding="utf-8")
    page = (PROJECT_ROOT / "static" / "index.html").read_text(encoding="utf-8")
    ui = (PROJECT_ROOT / "static" / "inference_soak.js").read_text(encoding="utf-8")
    script = (PROJECT_ROOT / "scripts" / "soak_inference_api.py").read_text(encoding="utf-8")
    smoke = (PROJECT_ROOT / "scripts" / "smoke_inference_soak.py").read_text(encoding="utf-8")

    assert '@router.post("/api/inference/soak/start")' in router
    assert '@router.get("/api/inference/soak/latest")' in router
    assert 'env["MORTAL_INFERENCE_API_KEY"] = api_key' in router
    soak_section = router.split('@router.post("/api/inference/soak/start")', 1)[1]
    assert '"--api-key"' not in soak_section
    assert '"--min-production-duration-s",\n            "1800"' in router
    assert '"--require-gpu-telemetry"' in router

    assert "inferenceSoakMinutes" in ui
    assert "inferenceSoakRequireGpu" in ui
    assert "startInferenceSoak" in ui
    assert "loadInferenceSoak" in ui
    assert "applyInferenceSoakPreset" in ui
    assert "Production gate는 최소 30분" in ui
    assert 'inference_soak.js' in page

    assert "MORTAL_INFERENCE_SOAK_OK" in script
    assert "MORTAL_INFERENCE_PRODUCTION_PRESET_OK" in script
    assert "nvidia-smi" in script
    assert "mortal-rogs-serving-soak-v1" in script
    assert "MORTAL_INFERENCE_SOAK_E2E_OK" in smoke
    assert "MORTAL_INFERENCE_PRODUCTION_PRESET_E2E_OK" in smoke
