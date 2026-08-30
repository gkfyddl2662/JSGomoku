from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


class InferenceBenchmarkBody(BaseModel):
    modes: str = "both"
    requests_per_mode: int = Field(default=64, ge=4, le=4096)
    concurrency: int = Field(default=8, ge=1, le=256)
    batch_rows: int = Field(default=1, ge=1, le=64)
    sweep: bool = False
    sweep_waits: str = "0,0.5,1,1.5,2"
    latency_budget_ms: float = Field(default=100.0, gt=0.0, le=1000.0)


class InferenceSoakBody(BaseModel):
    modes: str = "both"
    duration_minutes: float = Field(default=30.0, ge=0.05, le=1440.0)
    concurrency: int = Field(default=8, ge=1, le=256)
    batch_rows: int = Field(default=1, ge=1, le=64)
    sample_interval_s: float = Field(default=1.0, ge=0.2, le=60.0)
    latency_budget_ms: float = Field(default=100.0, gt=0.0, le=1000.0)
    p99_budget_ms: float = Field(default=250.0, gt=0.0, le=3500.0)
    vram_ceiling_pct: float = Field(default=92.0, ge=1.0, le=100.0)
    temperature_ceiling_c: float = Field(default=88.0, gt=0.0, le=120.0)
    reload_every_minutes: float = Field(default=0.0, ge=0.0, le=1440.0)
    require_gpu_telemetry: bool = True


def _connect_host(host: str) -> str:
    normalized = host.strip().casefold()
    return "127.0.0.1" if normalized in {"", "0.0.0.0", "::", "[::]"} else host.strip()


def _probe(server: str, api_key: str) -> dict[str, Any]:
    headers = {"Authorization": api_key} if api_key else {}
    request = urllib.request.Request(f"{server}/health", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=0.8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(409, f"Inference API must be running before benchmark: {exc}") from exc
    if payload.get("protocol") != "akagiot-v1":
        raise HTTPException(409, "Target is not the Mortal-ROGS Akagi inference API")
    lifecycle = payload.get("lifecycle", {}) or {}
    if lifecycle.get("state") not in {None, "running"}:
        raise HTTPException(409, f"Inference API is not accepting requests: {lifecycle.get('state')}")
    return payload


def create_inference_benchmark_router(settings: Any, controller: Any, jobs: Any, inference_target: dict[str, Any]) -> APIRouter:
    router = APIRouter()

    def unified_runtime():
        r3 = settings.runtime("3p")
        r4 = settings.runtime("4p")
        if not (r3.unified and r4.unified and r3.root == r4.root and r3.python_executable == r4.python_executable):
            raise HTTPException(400, "Inference benchmark requires the unified Mortal runtime")
        if not r3.python_executable.is_file():
            raise HTTPException(400, f"Unified Python runtime is missing: {r3.python_executable}")
        return r3

    def target() -> tuple[str, str]:
        host = str(inference_target.get("host", "127.0.0.1"))
        port = int(inference_target.get("port", 8190))
        api_key = str(inference_target.get("api_key", ""))
        server = f"http://{_connect_host(host)}:{port}"
        _probe(server, api_key)
        return server, api_key

    @router.post("/api/inference/benchmark/start")
    def start_benchmark(body: InferenceBenchmarkBody) -> dict[str, Any]:
        runtime = unified_runtime()
        modes = body.modes.strip().casefold()
        if modes not in {"3p", "4p", "both"}:
            raise HTTPException(400, "Benchmark modes must be 3p, 4p or both")
        if body.sweep and not body.sweep_waits.strip():
            raise HTTPException(400, "Sweep requires at least one micro-batch wait candidate")

        server, api_key = target()
        script = settings.project_root / "scripts" / "benchmark_inference_api.py"
        if not script.is_file():
            raise HTTPException(500, f"Inference benchmark script is missing: {script}")

        report_dir = runtime.root / "runtime" / "serving-benchmarks"
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        suffix = "sweep" if body.sweep else "single"
        report = report_dir / f"serving-{stamp}-{time.time_ns() % 1_000_000_000:09d}-{suffix}.json"

        command = [
            str(runtime.python_executable),
            str(script),
            "--server",
            server,
            "--modes",
            modes,
            "--requests",
            str(body.requests_per_mode),
            "--concurrency",
            str(body.concurrency),
            "--batch-rows",
            str(body.batch_rows),
            "--latency-budget-ms",
            str(body.latency_budget_ms),
            "--output",
            str(report),
        ]
        if body.sweep:
            command.extend(["--sweep-waits", body.sweep_waits.strip()])

        env = controller._mortal_env(runtime)
        if api_key:
            env["MORTAL_INFERENCE_API_KEY"] = api_key
        try:
            job = jobs.start("inference_benchmark_sweep" if body.sweep else "inference_benchmark", command, settings.project_root, env)
        except Exception as exc:
            raise HTTPException(400, str(exc)) from exc
        result = job.snapshot()
        result["report"] = str(report)
        result["sweep"] = body.sweep
        return result

    @router.get("/api/inference/benchmark/latest")
    def latest_benchmark() -> dict[str, Any]:
        runtime = unified_runtime()
        report_dir = runtime.root / "runtime" / "serving-benchmarks"
        files = sorted(
            (path for path in report_dir.glob("serving-*.json") if path.is_file()),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        ) if report_dir.is_dir() else []
        if not files:
            return {"available": False, "report": None, "path": None}
        latest = files[0]
        try:
            payload = json.loads(latest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HTTPException(500, f"Latest inference benchmark report is unreadable: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("protocol") != "mortal-rogs-serving-benchmark-v1":
            raise HTTPException(500, "Latest inference benchmark report has an unexpected schema")
        return {"available": True, "report": payload, "path": str(latest)}

    @router.post("/api/inference/soak/start")
    def start_soak(body: InferenceSoakBody) -> dict[str, Any]:
        runtime = unified_runtime()
        modes = body.modes.strip().casefold()
        if modes not in {"3p", "4p", "both"}:
            raise HTTPException(400, "Soak modes must be 3p, 4p or both")
        server, api_key = target()
        script = settings.project_root / "scripts" / "soak_inference_api.py"
        if not script.is_file():
            raise HTTPException(500, f"Inference soak script is missing: {script}")

        report_dir = runtime.root / "runtime" / "serving-benchmarks"
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        report = report_dir / f"soak-{stamp}-{time.time_ns() % 1_000_000_000:09d}.json"
        duration_s = body.duration_minutes * 60.0
        command = [
            str(runtime.python_executable),
            str(script),
            "--server",
            server,
            "--modes",
            modes,
            "--duration-s",
            str(duration_s),
            "--min-production-duration-s",
            "1800",
            "--concurrency",
            str(body.concurrency),
            "--batch-rows",
            str(body.batch_rows),
            "--sample-interval-s",
            str(body.sample_interval_s),
            "--latency-budget-ms",
            str(body.latency_budget_ms),
            "--p99-budget-ms",
            str(body.p99_budget_ms),
            "--vram-ceiling-pct",
            str(body.vram_ceiling_pct),
            "--temperature-ceiling-c",
            str(body.temperature_ceiling_c),
            "--reload-every-s",
            str(body.reload_every_minutes * 60.0),
            "--output",
            str(report),
        ]
        if body.require_gpu_telemetry:
            command.append("--require-gpu-telemetry")

        env = controller._mortal_env(runtime)
        if api_key:
            env["MORTAL_INFERENCE_API_KEY"] = api_key
        try:
            job = jobs.start("inference_soak", command, settings.project_root, env)
        except Exception as exc:
            raise HTTPException(400, str(exc)) from exc
        result = job.snapshot()
        result["report"] = str(report)
        result["duration_minutes"] = body.duration_minutes
        result["production_minimum_minutes"] = 30.0
        return result

    @router.get("/api/inference/soak/latest")
    def latest_soak() -> dict[str, Any]:
        runtime = unified_runtime()
        report_dir = runtime.root / "runtime" / "serving-benchmarks"
        files = sorted(
            (path for path in report_dir.glob("soak-*.json") if path.is_file()),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        ) if report_dir.is_dir() else []
        if not files:
            return {"available": False, "report": None, "path": None}
        latest = files[0]
        try:
            payload = json.loads(latest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HTTPException(500, f"Latest inference soak report is unreadable: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("protocol") != "mortal-rogs-serving-soak-v1":
            raise HTTPException(500, "Latest inference soak report has an unexpected schema")
        return {"available": True, "report": payload, "path": str(latest)}

    return router
