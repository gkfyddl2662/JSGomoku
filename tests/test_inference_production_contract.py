from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_module():
    path = PROJECT_ROOT / "app" / "inference_production.py"
    spec = importlib.util.spec_from_file_location("inference_production_contract", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def health_for(module, serving):
    serving = module.normalize_serving_settings(serving)
    return {
        "protocol": "akagiot-v1",
        "degraded": False,
        "lifecycle": {"state": "running", "accepting": True},
        "models": {
            "3p": {"loaded": True, "current": True, "last_error": None},
            "4p": {"loaded": True, "current": True, "last_error": None},
        },
        "serving": {
            "micro_batch": {
                "wait_ms": serving["micro_batch_ms"],
                "max_rows": serving["micro_batch_max_rows"],
                "max_pending_requests": serving["max_pending_requests"],
                "request_deadline_ms": serving["request_deadline_ms"],
            },
            "reload": {
                "poll_ms": serving["reload_poll_ms"],
                "quiet_ms": serving["reload_quiet_ms"],
                "wait_ms": serving["reload_wait_ms"],
            },
            "device_scheduler": {"max_parallel_executions": serving["max_device_executions"]},
            "drain_timeout_ms": serving["drain_timeout_ms"],
        },
    }


def test_profile_never_persists_api_key_and_requires_5080_serialization(tmp_path: Path) -> None:
    module = load_module()
    serving = module.normalize_serving_settings({"micro_batch_ms": 1.5, "max_device_executions": 1})
    target = {
        "host": "127.0.0.1",
        "port": 8190,
        "device": "cuda:0",
        "api_key": "super-secret",
        "serving": serving,
    }
    profile = module.build_profile(
        target,
        serving,
        source_report=tmp_path / "soak.json",
        source_payload={"protocol": module.SOAK_PROTOCOL},
    )
    encoded = json.dumps(profile)
    assert "super-secret" not in encoded
    assert "api_key" not in encoded
    assert profile["serving"]["max_device_executions"] == 1

    with pytest.raises(module.ProductionProfileError):
        module.normalize_serving_settings({"max_device_executions": 2})


def test_transaction_marks_profile_active_after_verified_restart(tmp_path: Path) -> None:
    module = load_module()
    path = tmp_path / "production.json"
    previous = {
        "host": "127.0.0.1",
        "port": 8190,
        "api_key": "secret",
        "device": "cpu",
        "serving": module.normalize_serving_settings({"micro_batch_ms": 0.0}),
    }
    candidate = {
        **previous,
        "serving": module.normalize_serving_settings({"micro_batch_ms": 1.0}),
    }
    profile = module.build_profile(
        candidate,
        candidate["serving"],
        source_report=tmp_path / "soak.json",
        source_payload={"protocol": module.SOAK_PROTOCOL},
    )
    events: list[str] = []

    ops = module.LifecycleOps(
        drain=lambda timeout_ms: events.append("drain") or {"drained": True},
        stop=lambda: events.append("stop") or {"stopped": True},
        start=lambda target: events.append(f"start:{target['serving']['micro_batch_ms']}") or {"id": "candidate"},
        wait_healthy=lambda target, timeout: health_for(module, target["serving"]),
    )
    result = module.apply_profile_transaction(
        path=path,
        candidate_profile=profile,
        previous_target=previous,
        candidate_target=candidate,
        ops=ops,
        verify_timeout_s=10.0,
    )
    assert result["ok"] is True
    assert result["rolled_back"] is False
    assert events == ["drain", "stop", "start:1.0"]
    stored = module.read_profile(path)
    assert stored is not None
    assert stored["status"] == "active"
    assert stored["serving"]["micro_batch_ms"] == 1.0


def test_transaction_restores_previous_profile_and_server_on_candidate_failure(tmp_path: Path) -> None:
    module = load_module()
    path = tmp_path / "production.json"
    old_profile = {
        "protocol": module.PROFILE_PROTOCOL,
        "status": "active",
        "serving": module.normalize_serving_settings({"micro_batch_ms": 0.0}),
    }
    module.atomic_write_profile(path, old_profile)
    old_bytes = path.read_bytes()

    previous = {
        "host": "127.0.0.1",
        "port": 8190,
        "api_key": "secret",
        "device": "cpu",
        "serving": module.normalize_serving_settings({"micro_batch_ms": 0.0}),
    }
    candidate = {
        **previous,
        "serving": module.normalize_serving_settings({"micro_batch_ms": 2.0}),
    }
    profile = module.build_profile(
        candidate,
        candidate["serving"],
        source_report=tmp_path / "soak.json",
        source_payload={"protocol": module.SOAK_PROTOCOL},
    )

    starts: list[float] = []
    waits = 0

    def start(target):
        starts.append(float(target["serving"]["micro_batch_ms"]))
        return {"id": f"start-{len(starts)}"}

    def wait_healthy(target, timeout):
        nonlocal waits
        waits += 1
        if waits == 1:
            raise RuntimeError("forced candidate boot failure")
        return health_for(module, target["serving"])

    ops = module.LifecycleOps(
        drain=lambda timeout_ms: {"drained": True},
        stop=lambda: {"stopped": True},
        start=start,
        wait_healthy=wait_healthy,
    )
    with pytest.raises(module.ProductionApplyError) as caught:
        module.apply_profile_transaction(
            path=path,
            candidate_profile=profile,
            previous_target=previous,
            candidate_target=candidate,
            ops=ops,
            verify_timeout_s=10.0,
        )
    assert caught.value.rollback["ok"] is True
    assert starts == [2.0, 0.0]
    assert path.read_bytes() == old_bytes


def test_control_center_production_apply_contract() -> None:
    router = (PROJECT_ROOT / "app" / "inference_benchmark.py").read_text(encoding="utf-8")
    core = (PROJECT_ROOT / "app" / "inference_production.py").read_text(encoding="utf-8")
    ui = (PROJECT_ROOT / "static" / "inference_soak.js").read_text(encoding="utf-8")

    assert '@router.post("/api/inference/production/apply")' in router
    assert '@router.get("/api/inference/production/status")' in router
    assert "latest_eligible_soak(runtime.root)" in router
    assert 'env["MORTAL_INFERENCE_API_KEY"] = api_key' in router
    production_section = router.split('@router.post("/api/inference/production/apply")', 1)[1]
    assert '"--api-key"' not in production_section
    for flag in (
        "--max-device-executions",
        "--reload-quiet-ms",
        "--reload-wait-ms",
        "--drain-timeout-ms",
    ):
        assert flag in router

    assert "os.replace(tmp, path)" in core
    assert "restore_profile(path, previous_bytes)" in core
    assert "Rollback health verification failed" in core
    assert "max_device_executions=1" in core

    assert "applyInferenceProductionProfile" in ui
    assert "/api/inference/production/apply" in ui
    assert "/api/inference/production/status" in ui
