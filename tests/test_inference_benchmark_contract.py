from __future__ import annotations

import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_benchmark_module():
    path = PROJECT_ROOT / "scripts" / "benchmark_inference_api.py"
    spec = importlib.util.spec_from_file_location("benchmark_inference_api", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_benchmark_contract_and_recommendation_are_mode_aware() -> None:
    benchmark = load_benchmark_module()
    assert benchmark.MODE_CONTRACTS["3p"] == {
        "endpoint": "/react_batch_3p",
        "obs_channels": 1010,
        "actions": 44,
    }
    assert benchmark.MODE_CONTRACTS["4p"] == {
        "endpoint": "/react_batch",
        "obs_channels": 1012,
        "actions": 46,
    }

    settings = {
        "micro_batch_ms": 1.0,
        "micro_batch_max_rows": 64,
        "max_pending_requests": 128,
        "request_deadline_ms": 3500.0,
        "reload_poll_ms": 500.0,
    }
    healthy = {
        "3p": {
            "error_rate": 0.0,
            "latency_ms": {"p95": 30.0},
            "observed_rows_per_execution": 1.2,
            "busy_rejections": 0,
        },
        "4p": {
            "error_rate": 0.0,
            "latency_ms": {"p95": 40.0},
            "observed_rows_per_execution": 1.1,
            "busy_rejections": 0,
        },
    }
    result = benchmark.recommend(settings, healthy, concurrency=8, batch_rows=1)
    assert result["kind"] == "heuristic"
    assert result["requires_ab_validation"] is True
    assert result["recommended"]["micro_batch_ms"] == 1.5
    assert result["recommended"]["request_deadline_ms"] < 4000

    overloaded = {
        "3p": {
            "error_rate": 0.1,
            "latency_ms": {"p95": 300.0},
            "observed_rows_per_execution": 4.0,
            "busy_rejections": 2,
        }
    }
    result = benchmark.recommend(settings, overloaded, concurrency=16, batch_rows=1)
    assert result["recommended"]["micro_batch_ms"] == 0.5
    assert result["recommended"]["max_pending_requests"] >= 256


def test_control_center_exposes_benchmark_without_leaking_api_key_in_process_args() -> None:
    router = (PROJECT_ROOT / "app" / "inference_benchmark.py").read_text(encoding="utf-8")
    main = (PROJECT_ROOT / "app" / "main.py").read_text(encoding="utf-8")
    ui = (PROJECT_ROOT / "static" / "inference.js").read_text(encoding="utf-8")
    script = (PROJECT_ROOT / "scripts" / "benchmark_inference_api.py").read_text(encoding="utf-8")

    assert '@router.post("/api/inference/benchmark/start")' in router
    assert '@router.get("/api/inference/benchmark/latest")' in router
    assert "create_inference_benchmark_router" in main
    assert "app.include_router" in main
    assert 'env["MORTAL_INFERENCE_API_KEY"] = api_key' in router
    assert '"--api-key"' not in router
    assert 'default=os.getenv("MORTAL_INFERENCE_API_KEY", "")' in script
    assert "MORTAL_INFERENCE_BENCHMARK_OK" in script

    assert "startInferenceBenchmark" in ui
    assert "loadInferenceBenchmark" in ui
    assert "applyInferenceBenchmarkRecommendation" in ui
    assert "inferenceBenchmarkConcurrency" in ui
    assert "inferenceBenchmarkRows" in ui
    assert "추천값을 Tuning에 적용" in ui
