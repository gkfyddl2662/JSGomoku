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


def test_sweep_prefers_safe_throughput_within_latency_budget() -> None:
    benchmark = load_benchmark_module()
    assert benchmark.parse_sweep_waits("0,0.5,1,0.5,2") == [0.0, 0.5, 1.0, 2.0]

    candidates = [
        {
            "micro_batch_ms": 0.0,
            "aggregate": {
                "rows_per_s": 800.0,
                "max_p95_ms": 30.0,
                "failed_requests": 0,
                "busy_rejections": 0,
                "timeouts": 0,
                "safe": True,
                "within_latency_budget": True,
            },
        },
        {
            "micro_batch_ms": 1.0,
            "aggregate": {
                "rows_per_s": 1200.0,
                "max_p95_ms": 55.0,
                "failed_requests": 0,
                "busy_rejections": 0,
                "timeouts": 0,
                "safe": True,
                "within_latency_budget": True,
            },
        },
        {
            "micro_batch_ms": 2.0,
            "aggregate": {
                "rows_per_s": 1500.0,
                "max_p95_ms": 140.0,
                "failed_requests": 0,
                "busy_rejections": 0,
                "timeouts": 0,
                "safe": True,
                "within_latency_budget": False,
            },
        },
    ]
    winner = benchmark.select_sweep_winner(candidates, latency_budget_ms=100.0)
    assert winner["micro_batch_ms"] == 1.0


def test_control_center_exposes_benchmark_sweep_without_leaking_api_key_in_process_args() -> None:
    router = (PROJECT_ROOT / "app" / "inference_benchmark.py").read_text(encoding="utf-8")
    main = (PROJECT_ROOT / "app" / "main.py").read_text(encoding="utf-8")
    ui = (PROJECT_ROOT / "static" / "inference.js").read_text(encoding="utf-8")
    script = (PROJECT_ROOT / "scripts" / "benchmark_inference_api.py").read_text(encoding="utf-8")
    server = (PROJECT_ROOT / "scripts" / "serve_akagi_api.py").read_text(encoding="utf-8")

    assert '@router.post("/api/inference/benchmark/start")' in router
    assert '@router.get("/api/inference/benchmark/latest")' in router
    assert "create_inference_benchmark_router" in main
    assert "app.include_router" in main
    assert 'env["MORTAL_INFERENCE_API_KEY"] = api_key' in router
    assert '"--api-key"' not in router
    assert 'default=os.getenv("MORTAL_INFERENCE_API_KEY", "")' in script
    assert "MORTAL_INFERENCE_BENCHMARK_OK" in script
    assert "MORTAL_INFERENCE_SWEEP_OK" in script
    assert "apply_micro_batch_wait" in script
    assert "original_restored" in script
    assert 'command.extend(["--sweep-waits"' in router

    assert '@app.post("/api/inference/tuning")' in server
    assert 'set(payload) - {"micro_batch_ms"}' in server
    assert "batcher._condition" in server
    assert '"models_reloaded": False' in server

    assert "startInferenceBenchmark" in ui
    assert "startInferenceSweep" in ui
    assert "loadInferenceBenchmark" in ui
    assert "applyInferenceBenchmarkRecommendation" in ui
    assert "inferenceBenchmarkConcurrency" in ui
    assert "inferenceBenchmarkRows" in ui
    assert "inferenceSweepWaits" in ui
    assert "inferenceLatencyBudget" in ui
    assert "추천값을 Tuning에 적용" in ui
    assert "original restored" in ui
