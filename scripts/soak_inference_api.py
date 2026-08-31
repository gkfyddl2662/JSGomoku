from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import time
from collections import Counter, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from benchmark_inference_api import (  # type: ignore
    MODE_CONTRACTS,
    build_payload,
    current_settings,
    latency_summary,
    parse_modes,
    post_json,
    request_json,
)

SOAK_PROTOCOL = "mortal-rogs-serving-soak-v1"
MAX_LATENCY_SAMPLES = 500_000


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ceil_step(value: float, step: float) -> float:
    return math.ceil(value / step) * step if step > 0 else value


def next_power_of_two(value: int) -> int:
    value = max(1, int(value))
    return 1 << (value - 1).bit_length()


def parse_nvidia_smi_line(line: str) -> dict[str, Any]:
    parts = [part.strip() for part in line.split(",")]
    if len(parts) != 7:
        raise ValueError(f"unexpected nvidia-smi field count: {len(parts)}")
    index, name, used, total, util, temperature, power = parts
    used_mb = float(used)
    total_mb = float(total)
    return {
        "available": True,
        "index": int(index),
        "name": name,
        "memory_used_mb": used_mb,
        "memory_total_mb": total_mb,
        "memory_used_pct": round(used_mb / total_mb * 100.0, 3) if total_mb > 0 else None,
        "utilization_pct": float(util),
        "temperature_c": float(temperature),
        "power_w": float(power),
    }


class NvidiaSampler:
    def __init__(self, gpu_index: int = 0) -> None:
        self.gpu_index = max(0, int(gpu_index))
        self.executable = shutil.which("nvidia-smi")

    def sample(self) -> dict[str, Any]:
        if self.executable is None:
            return {"available": False, "error": "nvidia-smi not found"}
        command = [
            self.executable,
            f"--id={self.gpu_index}",
            "--query-gpu=index,name,memory.used,memory.total,utilization.gpu,temperature.gpu,power.draw",
            "--format=csv,noheader,nounits",
        ]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=2.0, check=False)
            if completed.returncode != 0:
                return {"available": False, "error": completed.stderr.strip() or f"exit {completed.returncode}"}
            line = next((row.strip() for row in completed.stdout.splitlines() if row.strip()), "")
            if not line:
                return {"available": False, "error": "nvidia-smi returned no GPU row"}
            return parse_nvidia_smi_line(line)
        except Exception as exc:
            return {"available": False, "error": f"{type(exc).__name__}: {exc}"}


def gpu_index_from_health(health: dict[str, Any]) -> int:
    for mode in ("3p", "4p"):
        device = str((health.get("models", {}).get(mode, {}) or {}).get("device", ""))
        if device.casefold().startswith("cuda:"):
            try:
                return max(0, int(device.split(":", 1)[1]))
            except ValueError:
                pass
    return 0


def summarize_gpu(samples: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [sample.get("gpu", {}) for sample in samples if (sample.get("gpu", {}) or {}).get("available")]
    if not rows:
        errors = [str((sample.get("gpu", {}) or {}).get("error")) for sample in samples if (sample.get("gpu", {}) or {}).get("error")]
        return {"available": False, "samples": 0, "last_error": errors[-1] if errors else None}

    def values(key: str) -> list[float]:
        return [float(row[key]) for row in rows if row.get(key) is not None]

    used_mb = values("memory_used_mb")
    used_pct = values("memory_used_pct")
    util = values("utilization_pct")
    temp = values("temperature_c")
    power = values("power_w")
    first = rows[0]
    return {
        "available": True,
        "samples": len(rows),
        "index": first.get("index"),
        "name": first.get("name"),
        "memory_total_mb": first.get("memory_total_mb"),
        "peak_memory_used_mb": round(max(used_mb), 3) if used_mb else None,
        "peak_memory_used_pct": round(max(used_pct), 3) if used_pct else None,
        "avg_utilization_pct": round(sum(util) / len(util), 3) if util else None,
        "peak_utilization_pct": round(max(util), 3) if util else None,
        "peak_temperature_c": round(max(temp), 3) if temp else None,
        "peak_power_w": round(max(power), 3) if power else None,
    }


def mode_counter_delta(before: dict[str, Any], after: dict[str, Any], mode: str) -> dict[str, int]:
    a = (after.get("modes", {}).get(mode, {}) or {})
    b = (before.get("modes", {}).get(mode, {}) or {})
    keys = ("requests_total", "rows_total", "errors_total", "timeouts_total", "busy_rejections_total", "executions_total")
    return {key: max(0, int(a.get(key, 0) or 0) - int(b.get(key, 0) or 0)) for key in keys}


def device_snapshot(metrics: dict[str, Any]) -> dict[str, Any]:
    return dict(metrics.get("device_scheduler", {}) or {})


def compact_health_sample(elapsed_s: float, health: dict[str, Any], gpu: dict[str, Any]) -> dict[str, Any]:
    serving = health.get("serving", {}) or {}
    device = serving.get("device_scheduler", {}) or {}
    lifecycle = serving.get("lifecycle", health.get("lifecycle", {})) or {}
    modes = serving.get("modes", {}) or {}
    return {
        "elapsed_s": round(elapsed_s, 3),
        "degraded": bool(health.get("degraded")),
        "lifecycle": {
            "state": lifecycle.get("state"),
            "inflight": int(lifecycle.get("inflight_requests", 0) or 0),
            "peak_inflight": int(lifecycle.get("peak_inflight_requests", 0) or 0),
        },
        "device": {
            "active": int(device.get("active_executions", 0) or 0),
            "waiting": int(device.get("waiting_executions", 0) or 0),
            "peak_active": int(device.get("peak_active_executions", 0) or 0),
            "peak_waiting": int(device.get("peak_waiting_executions", 0) or 0),
            "wait_p95_ms": (device.get("wait_ms", {}) or {}).get("p95"),
            "maintenance_active": bool(device.get("maintenance_active")),
            "maintenance_waiting": int(device.get("maintenance_waiting", 0) or 0),
        },
        "modes": {
            mode: {
                "queue_depth": int((modes.get(mode, {}) or {}).get("queue_depth", 0) or 0),
                "peak_queue_depth": int((modes.get(mode, {}) or {}).get("peak_queue_depth", 0) or 0),
                "timeouts_total": int((modes.get(mode, {}) or {}).get("timeouts_total", 0) or 0),
                "busy_rejections_total": int((modes.get(mode, {}) or {}).get("busy_rejections_total", 0) or 0),
            }
            for mode in ("3p", "4p")
        },
        "gpu": gpu,
    }


def derive_production_preset(
    settings: dict[str, Any],
    mode_results: dict[str, dict[str, Any]],
    samples: list[dict[str, Any]],
    *,
    concurrency: int,
) -> dict[str, Any]:
    p99_values = [
        float(result.get("latency_ms", {}).get("p99"))
        for result in mode_results.values()
        if result.get("latency_ms", {}).get("p99") is not None
    ]
    p99 = max(p99_values) if p99_values else 250.0
    peak_queue = 0
    for sample in samples:
        for mode in ("3p", "4p"):
            peak_queue = max(peak_queue, int((sample.get("modes", {}).get(mode, {}) or {}).get("peak_queue_depth", 0) or 0))

    pending_target = next_power_of_two(max(int(settings.get("max_pending_requests", 128)), concurrency * 8, (peak_queue + concurrency) * 4))
    deadline = min(3500.0, max(1000.0, ceil_step(p99 * 4.0, 50.0)))
    reload_quiet = min(750.0, max(150.0, ceil_step(p99 * 1.5, 25.0)))
    reload_wait = min(3000.0, max(1000.0, ceil_step(p99 * 8.0, 50.0)))
    return {
        "micro_batch_ms": float(settings.get("micro_batch_ms", 1.0)),
        "micro_batch_max_rows": max(64, int(settings.get("micro_batch_max_rows", 64))),
        "max_pending_requests": min(512, pending_target),
        "request_deadline_ms": deadline,
        "reload_poll_ms": float(settings.get("reload_poll_ms", 500.0)),
        "max_device_executions": 1,
        "reload_quiet_ms": reload_quiet,
        "reload_wait_ms": reload_wait,
        "drain_timeout_ms": min(3500.0, max(deadline, float(settings.get("drain_timeout_ms", 3500.0)))),
    }


def evaluate_production_gate(
    mode_results: dict[str, dict[str, Any]],
    server_deltas: dict[str, dict[str, int]],
    device: dict[str, Any],
    gpu: dict[str, Any],
    samples: list[dict[str, Any]],
    *,
    elapsed_s: float,
    min_duration_s: float,
    latency_budget_ms: float,
    p99_budget_ms: float,
    vram_ceiling_pct: float,
    temperature_ceiling_c: float,
    require_gpu_telemetry: bool,
    model_signature_changed: bool,
    reload_failures: int,
) -> dict[str, Any]:
    failed_requests = sum(int(result.get("failed_requests", 0) or 0) for result in mode_results.values())
    p95_values = [float(result["latency_ms"]["p95"]) for result in mode_results.values() if result.get("latency_ms", {}).get("p95") is not None]
    p99_values = [float(result["latency_ms"]["p99"]) for result in mode_results.values() if result.get("latency_ms", {}).get("p99") is not None]
    max_p95 = max(p95_values) if p95_values else math.inf
    max_p99 = max(p99_values) if p99_values else math.inf
    busy = sum(int(row.get("busy_rejections_total", 0) or 0) for row in server_deltas.values())
    timeouts = sum(int(row.get("timeouts_total", 0) or 0) for row in server_deltas.values())
    degraded_samples = sum(1 for sample in samples if sample.get("degraded"))
    max_parallel = max(1, int(device.get("max_parallel_executions", 1) or 1))
    peak_active = int(device.get("peak_active_executions", 0) or 0)
    gpu_available = bool(gpu.get("available"))
    vram = gpu.get("peak_memory_used_pct")
    temp = gpu.get("peak_temperature_c")

    checks = {
        "minimum_duration": elapsed_s >= min_duration_s,
        "requests_clean": failed_requests == 0,
        "server_busy_rejections": busy == 0,
        "server_timeouts": timeouts == 0,
        "p95_latency": math.isfinite(max_p95) and max_p95 <= latency_budget_ms,
        "p99_latency": math.isfinite(max_p99) and max_p99 <= p99_budget_ms,
        "device_serialization": peak_active <= max_parallel,
        "health_not_degraded": degraded_samples == 0,
        "model_signature_stable": not model_signature_changed,
        "reload_stress_clean": reload_failures == 0,
        "gpu_telemetry": gpu_available or not require_gpu_telemetry,
        "vram_headroom": (not gpu_available) or (vram is not None and float(vram) <= vram_ceiling_pct),
        "temperature": (not gpu_available) or (temp is not None and float(temp) <= temperature_ceiling_c),
    }
    duration_ok = checks["minimum_duration"]
    non_duration_ok = all(value for key, value in checks.items() if key != "minimum_duration")
    passed = duration_ok and non_duration_ok
    validation_level = "production" if passed else ("smoke" if non_duration_ok and not duration_ok else "failed")
    return {
        "passed": passed,
        "validation_level": validation_level,
        "checks": checks,
        "observed": {
            "elapsed_s": round(elapsed_s, 3),
            "minimum_duration_s": min_duration_s,
            "failed_requests": failed_requests,
            "busy_rejections": busy,
            "timeouts": timeouts,
            "max_p95_ms": round(max_p95, 3) if math.isfinite(max_p95) else None,
            "max_p99_ms": round(max_p99, 3) if math.isfinite(max_p99) else None,
            "degraded_samples": degraded_samples,
            "peak_active_executions": peak_active,
            "max_parallel_executions": max_parallel,
            "reload_failures_or_deferred": reload_failures,
            "gpu_available": gpu_available,
            "peak_vram_pct": vram,
            "peak_temperature_c": temp,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Long-running mixed 3P/4P Mortal-ROGS serving soak.")
    parser.add_argument("--server", default="http://127.0.0.1:8190")
    parser.add_argument("--api-key", default=os.getenv("MORTAL_INFERENCE_API_KEY", ""))
    parser.add_argument("--modes", default="both")
    parser.add_argument("--duration-s", type=float, default=1800.0)
    parser.add_argument("--min-production-duration-s", type=float, default=1800.0)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--batch-rows", type=int, default=1)
    parser.add_argument("--sample-interval-s", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=4.0)
    parser.add_argument("--latency-budget-ms", type=float, default=100.0)
    parser.add_argument("--p99-budget-ms", type=float, default=250.0)
    parser.add_argument("--vram-ceiling-pct", type=float, default=92.0)
    parser.add_argument("--temperature-ceiling-c", type=float, default=88.0)
    parser.add_argument("--reload-every-s", type=float, default=0.0)
    parser.add_argument("--require-gpu-telemetry", action="store_true")
    parser.add_argument("--fail-on-gate", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.duration_s <= 0 or args.min_production_duration_s <= 0:
        raise SystemExit("duration values must be > 0")
    if args.concurrency < 1 or args.batch_rows < 1:
        raise SystemExit("concurrency and batch rows must be >= 1")
    if args.sample_interval_s <= 0 or args.timeout <= 0:
        raise SystemExit("sample interval and timeout must be > 0")

    server = args.server.rstrip("/")
    modes = parse_modes(args.modes)
    status, initial_health, _ = request_json(f"{server}/health", api_key=args.api_key, timeout=args.timeout)
    if status != 200 or initial_health.get("protocol") != "akagiot-v1":
        raise SystemExit(f"Mortal inference API is not healthy: HTTP {status}: {initial_health}")
    lifecycle = initial_health.get("lifecycle", {}) or {}
    if lifecycle.get("state") not in {None, "running"}:
        raise SystemExit(f"Inference API is not accepting requests: {lifecycle}")
    status, before_metrics, _ = request_json(f"{server}/api/inference/metrics", api_key=args.api_key, timeout=args.timeout)
    if status != 200:
        raise SystemExit(f"Managed metrics unavailable: HTTP {status}")

    settings = current_settings(before_metrics)
    reload_cfg = before_metrics.get("reload", {}) or {}
    device_cfg = before_metrics.get("device_scheduler", {}) or {}
    settings.update({
        "max_device_executions": int(device_cfg.get("max_parallel_executions", 1) or 1),
        "reload_quiet_ms": float(reload_cfg.get("quiet_ms", 150.0) or 150.0),
        "reload_wait_ms": float(reload_cfg.get("wait_ms", 1000.0) or 1000.0),
        "drain_timeout_ms": float(before_metrics.get("drain_timeout_ms", 3500.0) or 3500.0),
    })
    initial_signatures = {mode: (initial_health.get("models", {}).get(mode, {}) or {}).get("loaded_signature") for mode in ("3p", "4p")}
    sampler = NvidiaSampler(gpu_index_from_health(initial_health))
    payloads = {mode: build_payload(mode, args.batch_rows) for mode in modes}

    stats: dict[str, dict[str, Any]] = {
        mode: {"requests": 0, "successful": 0, "rows": 0, "client_errors": 0, "statuses": Counter(), "latencies": deque(maxlen=MAX_LATENCY_SAMPLES)}
        for mode in modes
    }
    samples: list[dict[str, Any]] = []
    reload_events: list[dict[str, Any]] = []
    lock = threading.Lock()
    stop_event = threading.Event()
    started_at = utc_now()
    started = time.monotonic()
    deadline = started + args.duration_s

    def worker(index: int) -> None:
        cursor = index % len(modes)
        while not stop_event.is_set() and time.monotonic() < deadline:
            mode = modes[cursor % len(modes)]
            cursor += 1
            endpoint = str(MODE_CONTRACTS[mode]["endpoint"])
            try:
                code, body, latency = request_json(f"{server}{endpoint}", api_key=args.api_key, body=payloads[mode], timeout=args.timeout)
                ok = code == 200 and isinstance(body.get("actions"), list) and len(body["actions"]) == args.batch_rows
                with lock:
                    row = stats[mode]
                    row["requests"] += 1
                    row["statuses"][str(code)] += 1
                    row["latencies"].append(float(latency))
                    if ok:
                        row["successful"] += 1
                        row["rows"] += args.batch_rows
                    elif code == 200:
                        row["client_errors"] += 1
            except Exception:
                with lock:
                    row = stats[mode]
                    row["requests"] += 1
                    row["client_errors"] += 1
                    row["statuses"]["client_error"] += 1

    def monitor() -> None:
        while not stop_event.is_set() and time.monotonic() < deadline:
            elapsed = time.monotonic() - started
            try:
                code, health, _ = request_json(f"{server}/health", api_key=args.api_key, timeout=args.timeout)
                if code != 200:
                    health = {"degraded": True}
            except Exception:
                health = {"degraded": True}
            sample = compact_health_sample(elapsed, health, sampler.sample())
            with lock:
                samples.append(sample)
            stop_event.wait(min(args.sample_interval_s, max(0.001, deadline - time.monotonic())))

    def reload_stress() -> None:
        if args.reload_every_s <= 0:
            return
        next_at = started + args.reload_every_s
        index = 0
        while not stop_event.is_set():
            remaining = next_at - time.monotonic()
            if remaining > 0 and stop_event.wait(remaining):
                return
            if time.monotonic() >= deadline:
                return
            mode = modes[index % len(modes)]
            index += 1
            event: dict[str, Any] = {"elapsed_s": round(time.monotonic() - started, 3), "mode": mode}
            try:
                code, body = post_json(f"{server}/api/inference/reload", {"mode": mode}, api_key=args.api_key, timeout=max(args.timeout, 180.0))
                event.update({"status": code, "ok": code == 200 and body.get("ok") is True, "deferred": code == 409})
            except Exception as exc:
                event.update({"status": None, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
            with lock:
                reload_events.append(event)
            next_at += args.reload_every_s

    monitor_thread = threading.Thread(target=monitor, name="mortal-rogs-soak-monitor", daemon=True)
    reload_thread = threading.Thread(target=reload_stress, name="mortal-rogs-soak-reload", daemon=True)
    workers = [threading.Thread(target=worker, args=(i,), name=f"mortal-rogs-soak-{i}", daemon=True) for i in range(args.concurrency)]
    monitor_thread.start()
    reload_thread.start()
    for thread in workers:
        thread.start()
    try:
        while time.monotonic() < deadline and all(thread.is_alive() for thread in workers):
            time.sleep(min(0.25, max(0.01, deadline - time.monotonic())))
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        for thread in workers:
            thread.join(timeout=max(2.0, args.timeout + 1.0))
        monitor_thread.join(timeout=max(2.0, args.timeout + 1.0))
        reload_thread.join(timeout=max(2.0, args.timeout + 1.0))

    elapsed_s = max(0.001, time.monotonic() - started)
    try:
        _, final_health, _ = request_json(f"{server}/health", api_key=args.api_key, timeout=args.timeout)
    except Exception:
        final_health = {}
    try:
        _, after_metrics, _ = request_json(f"{server}/api/inference/metrics", api_key=args.api_key, timeout=args.timeout)
    except Exception:
        after_metrics = {}

    final_signatures = {mode: (final_health.get("models", {}).get(mode, {}) or {}).get("loaded_signature") for mode in ("3p", "4p")}
    signature_changed = any(initial_signatures.get(mode) != final_signatures.get(mode) for mode in ("3p", "4p") if initial_signatures.get(mode) is not None or final_signatures.get(mode) is not None)

    with lock:
        mode_results: dict[str, dict[str, Any]] = {}
        for mode, row in stats.items():
            requests = int(row["requests"])
            successful = int(row["successful"])
            mode_results[mode] = {
                "requests": requests,
                "successful_requests": successful,
                "failed_requests": max(0, requests - successful),
                "successful_rows": int(row["rows"]),
                "client_errors": int(row["client_errors"]),
                "status_counts": dict(row["statuses"]),
                "error_rate": round((requests - successful) / requests, 6) if requests else 1.0,
                "requests_per_s": round(successful / elapsed_s, 3),
                "rows_per_s": round(int(row["rows"]) / elapsed_s, 3),
                "latency_ms": latency_summary(list(row["latencies"])),
                "latency_samples_retained": len(row["latencies"]),
            }
        sample_copy = list(samples)
        reload_copy = list(reload_events)

    server_deltas = {mode: mode_counter_delta(before_metrics, after_metrics, mode) for mode in modes}
    device = device_snapshot(after_metrics)
    gpu = summarize_gpu(sample_copy)
    reload_failures = sum(1 for event in reload_copy if not event.get("ok"))
    gate = evaluate_production_gate(
        mode_results,
        server_deltas,
        device,
        gpu,
        sample_copy,
        elapsed_s=elapsed_s,
        min_duration_s=args.min_production_duration_s,
        latency_budget_ms=args.latency_budget_ms,
        p99_budget_ms=args.p99_budget_ms,
        vram_ceiling_pct=args.vram_ceiling_pct,
        temperature_ceiling_c=args.temperature_ceiling_c,
        require_gpu_telemetry=args.require_gpu_telemetry,
        model_signature_changed=signature_changed,
        reload_failures=reload_failures,
    )
    preset = derive_production_preset(settings, mode_results, sample_copy, concurrency=args.concurrency)
    report = {
        "protocol": SOAK_PROTOCOL,
        "server": server,
        "started_at": started_at,
        "finished_at": utc_now(),
        "elapsed_s": round(elapsed_s, 3),
        "workload": {
            "modes": modes,
            "duration_s": args.duration_s,
            "concurrency": args.concurrency,
            "batch_rows": args.batch_rows,
            "sample_interval_s": args.sample_interval_s,
            "gzip": True,
            "reload_every_s": args.reload_every_s,
        },
        "limits": {
            "min_production_duration_s": args.min_production_duration_s,
            "latency_budget_ms": args.latency_budget_ms,
            "p99_budget_ms": args.p99_budget_ms,
            "vram_ceiling_pct": args.vram_ceiling_pct,
            "temperature_ceiling_c": args.temperature_ceiling_c,
            "require_gpu_telemetry": args.require_gpu_telemetry,
        },
        "settings": settings,
        "modes": mode_results,
        "server_delta": server_deltas,
        "device_scheduler": device,
        "gpu": gpu,
        "models": {"initial_signatures": initial_signatures, "final_signatures": final_signatures, "signature_changed": signature_changed},
        "reload_stress": {"enabled": args.reload_every_s > 0, "attempts": len(reload_copy), "failures_or_deferred": reload_failures, "events": reload_copy},
        "samples": sample_copy,
        "production_gate": gate,
        "production_preset": {"eligible": bool(gate["passed"]), "settings": preset, "source": "measured_soak"},
    }

    if args.output is not None:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["output"] = str(output)

    print("MORTAL_INFERENCE_SOAK_OK")
    if gate["passed"]:
        print("MORTAL_INFERENCE_PRODUCTION_PRESET_OK")
    else:
        print("MORTAL_INFERENCE_PRODUCTION_GATE_FAILED")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if args.fail_on_gate and not gate["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
