from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .inference_production import (
    LifecycleOps,
    ProductionApplyError,
    ProductionProfileError,
    apply_profile_transaction,
    build_profile,
    latest_eligible_soak,
    normalize_serving_settings,
    profile_path,
    read_profile,
)
from .inference_recovery import compare_profile_health, target_from_active_profile


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


class InferenceProductionApplyBody(BaseModel):
    verify_timeout_s: float = Field(default=180.0, ge=10.0, le=600.0)


class InferenceProductionStartBody(BaseModel):
    api_key: str = ""
    verify_timeout_s: float = Field(default=180.0, ge=10.0, le=600.0)


def _connect_host(host: str) -> str:
    normalized = host.strip().casefold()
    return "127.0.0.1" if normalized in {"", "0.0.0.0", "::", "[::]"} else host.strip()


def _request_json(
    url: str,
    *,
    api_key: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 0.8,
) -> tuple[int, dict[str, Any]]:
    headers = {"Authorization": api_key} if api_key else {}
    data = None
    if payload is not None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            body = json.loads(raw) if raw else {}
            return int(response.status), body if isinstance(body, dict) else {"raw": body}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"raw": raw}
        return int(exc.code), body if isinstance(body, dict) else {"raw": body}


def _probe(server: str, api_key: str) -> dict[str, Any]:
    try:
        status, payload = _request_json(f"{server}/health", api_key=api_key, timeout=0.8)
    except (OSError, urllib.error.URLError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(409, f"Inference API must be running before benchmark: {exc}") from exc
    if status != 200 or payload.get("protocol") != "akagiot-v1":
        raise HTTPException(409, f"Target is not the Mortal-ROGS Akagi inference API: HTTP {status}")
    lifecycle = payload.get("lifecycle", {}) or {}
    if lifecycle.get("state") not in {None, "running"}:
        raise HTTPException(409, f"Inference API is not accepting requests: {lifecycle.get('state')}")
    return payload


def _device_from_health(health: dict[str, Any]) -> str:
    for mode in ("3p", "4p"):
        device = str((health.get("models", {}).get(mode, {}) or {}).get("device", "")).strip()
        if device:
            return device
    return "auto"


def create_inference_benchmark_router(settings: Any, controller: Any, jobs: Any, inference_target: dict[str, Any]) -> APIRouter:
    router = APIRouter()
    production_lock = threading.Lock()

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

    def current_inference_job() -> dict[str, Any] | None:
        for row in jobs.list():
            if row.get("kind") == "inference_api" and row.get("running"):
                return row
        return None

    def publish_job_id(job_id: str | None) -> None:
        module = sys.modules.get("app.main") or sys.modules.get("__main__")
        if module is not None and hasattr(module, "_inference_job_id"):
            setattr(module, "_inference_job_id", job_id)

    def update_target(new_target: dict[str, Any]) -> None:
        inference_target["host"] = str(new_target.get("host", "127.0.0.1"))
        inference_target["port"] = int(new_target.get("port", 8190))
        inference_target["api_key"] = str(new_target.get("api_key", ""))
        inference_target["device"] = str(new_target.get("device", "auto"))
        inference_target["serving"] = normalize_serving_settings(new_target.get("serving"))

    def server_command(runtime: Any, new_target: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
        serving = normalize_serving_settings(new_target.get("serving"))
        script = settings.project_root / "scripts" / "serve_akagi_api.py"
        if not script.is_file():
            raise RuntimeError(f"Inference API script is missing: {script}")
        command = [
            str(runtime.python_executable),
            str(script),
            "--runtime-root",
            str(runtime.root),
            "--host",
            str(new_target.get("host", "127.0.0.1")),
            "--port",
            str(int(new_target.get("port", 8190))),
            "--device",
            str(new_target.get("device", "auto")),
            "--micro-batch-ms",
            str(serving["micro_batch_ms"]),
            "--micro-batch-max-rows",
            str(serving["micro_batch_max_rows"]),
            "--max-pending-requests",
            str(serving["max_pending_requests"]),
            "--request-deadline-ms",
            str(serving["request_deadline_ms"]),
            "--reload-poll-ms",
            str(serving["reload_poll_ms"]),
            "--max-device-executions",
            str(serving["max_device_executions"]),
            "--reload-quiet-ms",
            str(serving["reload_quiet_ms"]),
            "--reload-wait-ms",
            str(serving["reload_wait_ms"]),
            "--drain-timeout-ms",
            str(serving["drain_timeout_ms"]),
        ]
        env = controller._mortal_env(runtime)
        api_key = str(new_target.get("api_key", ""))
        if api_key:
            env["MORTAL_INFERENCE_API_KEY"] = api_key
        return command, env

    def start_server(runtime: Any, new_target: dict[str, Any]) -> dict[str, Any]:
        command, env = server_command(runtime, new_target)
        job = jobs.start("inference_api", command, settings.project_root, env)
        publish_job_id(job.id)
        update_target(new_target)
        return job.snapshot()

    def stop_server() -> dict[str, Any]:
        row = current_inference_job()
        if row is None:
            publish_job_id(None)
            return {"stopped": False, "reason": "no running Control-Center-managed inference API"}
        result = jobs.stop(str(row["id"]))
        publish_job_id(None)
        return result

    def wait_healthy(new_target: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        host = str(new_target.get("host", "127.0.0.1"))
        port = int(new_target.get("port", 8190))
        api_key = str(new_target.get("api_key", ""))
        server = f"http://{_connect_host(host)}:{port}"
        deadline = time.monotonic() + timeout_s
        latest: dict[str, Any] = {}
        while time.monotonic() < deadline:
            row = current_inference_job()
            if row is None:
                raise RuntimeError("Inference API process exited before health verification")
            try:
                status, latest = _request_json(f"{server}/health", api_key=api_key, timeout=1.0)
                if status == 200 and latest.get("protocol") == "akagiot-v1":
                    lifecycle = latest.get("lifecycle", {}) or {}
                    if lifecycle.get("state") == "running" and lifecycle.get("accepting") is True:
                        return latest
            except (OSError, urllib.error.URLError, json.JSONDecodeError, UnicodeDecodeError):
                pass
            time.sleep(0.25)
        raise RuntimeError(f"Inference API did not become healthy within {timeout_s:g}s: {latest}")

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

    @router.get("/api/inference/production/status")
    def production_status() -> dict[str, Any]:
        runtime = unified_runtime()
        path = profile_path(runtime.root)
        try:
            profile = read_profile(path)
        except ProductionProfileError as exc:
            raise HTTPException(500, str(exc)) from exc
        if profile is None:
            return {"available": False, "profile": None, "path": str(path), "live": None}

        managed = current_inference_job() is not None
        key = str(inference_target.get("api_key", ""))
        saved = target_from_active_profile(profile, api_key=key)
        server = f"http://{_connect_host(saved['host'])}:{saved['port']}"
        live: dict[str, Any] = {"running": False, "managed": managed, "verified": False, "matches": False, "drift": ["offline"]}
        try:
            status, health = _request_json(f"{server}/health", api_key=key, timeout=0.6)
            if status == 200 and health.get("protocol") == "akagiot-v1":
                live = {"running": True, "managed": managed, **compare_profile_health(profile, health)}
            elif status == 401:
                live = {"running": True, "managed": managed, "verified": False, "matches": False, "drift": ["authorization"]}
            else:
                live = {"running": True, "managed": managed, "verified": False, "matches": False, "drift": [f"http:{status}"]}
        except (OSError, urllib.error.URLError, json.JSONDecodeError, UnicodeDecodeError):
            pass
        return {"available": True, "profile": profile, "path": str(path), "live": live}

    @router.post("/api/inference/production/start")
    def start_saved_production(body: InferenceProductionStartBody) -> dict[str, Any]:
        runtime = unified_runtime()
        if not production_lock.acquire(blocking=False):
            raise HTTPException(409, "A production serving profile transaction is already running")
        try:
            for row in jobs.list():
                if row.get("running") and row.get("kind") in {"inference_soak", "inference_benchmark", "inference_benchmark_sweep"}:
                    raise HTTPException(409, f"Stop {row.get('kind')} before restoring a production profile")

            path = profile_path(runtime.root)
            profile = read_profile(path)
            if profile is None:
                raise HTTPException(409, "No active production serving profile exists")
            saved_target = target_from_active_profile(profile, api_key=body.api_key)

            managed = current_inference_job()
            if managed is not None:
                current_key = str(inference_target.get("api_key", ""))
                current_host = str(inference_target.get("host", saved_target["host"]))
                current_port = int(inference_target.get("port", saved_target["port"]))
                current_server = f"http://{_connect_host(current_host)}:{current_port}"
                try:
                    status, health = _request_json(f"{current_server}/health", api_key=current_key, timeout=0.8)
                except (OSError, urllib.error.URLError, json.JSONDecodeError, UnicodeDecodeError):
                    status, health = 0, {}
                same_target = current_host == saved_target["host"] and current_port == saved_target["port"]
                if status == 200 and same_target and not verify_profile_drift(profile, health) and current_key == body.api_key:
                    update_target(saved_target)
                    return {"ok": True, "already_running": True, "managed": True, "profile": profile, "health": health, "job": managed}
                raise HTTPException(409, "A managed inference API is already running with a different or unverified profile; stop it or use production apply")

            server = f"http://{_connect_host(saved_target['host'])}:{saved_target['port']}"
            try:
                status, _ = _request_json(f"{server}/health", api_key=body.api_key, timeout=0.6)
                if status:
                    raise HTTPException(409, "An unmanaged process is already listening on the saved production server address")
            except HTTPException:
                raise
            except (OSError, urllib.error.URLError, json.JSONDecodeError, UnicodeDecodeError):
                pass

            started: dict[str, Any] | None = None
            try:
                started = start_server(runtime, saved_target)
                health = wait_healthy(saved_target, body.verify_timeout_s)
                comparison = compare_profile_health(profile, health)
                if not comparison["matches"]:
                    raise RuntimeError(f"Restored server does not match production profile: {comparison['drift']}")
            except Exception as exc:
                if started is not None:
                    try:
                        stop_server()
                    except Exception:
                        pass
                raise HTTPException(409, f"Production profile restore failed: {type(exc).__name__}: {exc}") from exc

            update_target(saved_target)
            return {
                "ok": True,
                "already_running": False,
                "managed": True,
                "profile": profile,
                "health": health,
                "job": current_inference_job(),
            }
        except ProductionProfileError as exc:
            raise HTTPException(409, str(exc)) from exc
        finally:
            production_lock.release()

    @router.post("/api/inference/production/apply")
    def apply_production(body: InferenceProductionApplyBody) -> dict[str, Any]:
        runtime = unified_runtime()
        if not production_lock.acquire(blocking=False):
            raise HTTPException(409, "A production serving profile transaction is already running")
        try:
            running = current_inference_job()
            if running is None:
                raise HTTPException(409, "Production apply requires a Control-Center-managed inference API job")
            for row in jobs.list():
                if row.get("running") and row.get("kind") in {"inference_soak", "inference_benchmark", "inference_benchmark_sweep"}:
                    raise HTTPException(409, f"Stop {row.get('kind')} before applying a production profile")

            host = str(inference_target.get("host", "127.0.0.1"))
            port = int(inference_target.get("port", 8190))
            api_key = str(inference_target.get("api_key", ""))
            server = f"http://{_connect_host(host)}:{port}"
            live_health = _probe(server, api_key)

            previous_target = {
                "host": host,
                "port": port,
                "api_key": api_key,
                "device": str(inference_target.get("device") or _device_from_health(live_health)),
                "serving": normalize_serving_settings(inference_target.get("serving")),
            }
            report_path, report, serving = latest_eligible_soak(runtime.root)
            candidate_target = {
                **previous_target,
                "serving": serving,
            }
            candidate_profile = build_profile(
                candidate_target,
                serving,
                source_report=report_path,
                source_payload=report,
            )

            def drain_current(timeout_ms: float) -> dict[str, Any]:
                try:
                    status, payload = _request_json(
                        f"{server}/api/inference/drain",
                        api_key=api_key,
                        payload={"timeout_ms": timeout_ms},
                        timeout=max(5.0, timeout_ms / 1000.0 + 2.0),
                    )
                except (OSError, urllib.error.URLError) as exc:
                    raise RuntimeError(f"Could not request graceful drain: {exc}") from exc
                if status != 200 or payload.get("ok") is not True:
                    raise RuntimeError(f"Graceful drain failed: HTTP {status}: {payload}")
                return dict(payload.get("drain", {}) or {})

            ops = LifecycleOps(
                drain=drain_current,
                stop=stop_server,
                start=lambda new_target: start_server(runtime, new_target),
                wait_healthy=wait_healthy,
            )
            try:
                result = apply_profile_transaction(
                    path=profile_path(runtime.root),
                    candidate_profile=candidate_profile,
                    previous_target=previous_target,
                    candidate_target=candidate_target,
                    ops=ops,
                    verify_timeout_s=body.verify_timeout_s,
                )
            except ProductionApplyError as exc:
                if exc.rollback.get("ok") is True:
                    update_target(previous_target)
                raise HTTPException(
                    409,
                    detail={
                        "message": str(exc),
                        "rolled_back": bool(exc.rollback.get("ok")),
                        "rollback": exc.rollback,
                    },
                ) from exc

            update_target(candidate_target)
            result["source_report"] = str(report_path)
            result["job"] = current_inference_job()
            return result
        except ProductionProfileError as exc:
            raise HTTPException(409, str(exc)) from exc
        finally:
            production_lock.release()

    return router


def verify_profile_drift(profile: dict[str, Any], health: dict[str, Any]) -> list[str]:
    return list(compare_profile_health(profile, health).get("drift", []))
