from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


MODE_CONTRACTS = {
    "3p": {"endpoint": "/react_batch_3p", "obs_channels": 1010, "actions": 44},
    "4p": {"endpoint": "/react_batch", "obs_channels": 1012, "actions": 46},
}


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return round(ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction, 3)


def latency_summary(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "p50": None, "p95": None, "p99": None, "max": None}
    return {
        "mean": round(statistics.fmean(values), 3),
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "max": round(max(values), 3),
    }


def request_json(
    url: str,
    *,
    api_key: str = "",
    body: bytes | None = None,
    timeout: float = 4.0,
) -> tuple[int, dict[str, Any], float]:
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = api_key
    if body is not None:
        headers["Content-Type"] = "application/json"
        headers["Content-Encoding"] = "gzip"
    request = urllib.request.Request(url, data=body, headers=headers, method="POST" if body is not None else "GET")
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return int(response.status), payload, (time.perf_counter() - started) * 1000.0
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"raw": raw}
        return int(exc.code), payload, (time.perf_counter() - started) * 1000.0


def post_json(url: str, payload: dict[str, Any], *, api_key: str = "", timeout: float = 4.0) -> tuple[int, dict[str, Any]]:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = api_key
    request = urllib.request.Request(url, data=raw, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status), json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            decoded = json.loads(body)
        except json.JSONDecodeError:
            decoded = {"raw": body}
        return int(exc.code), decoded


def apply_micro_batch_wait(server: str, api_key: str, wait_ms: float, timeout: float) -> dict[str, Any]:
    status, body = post_json(
        f"{server}/api/inference/tuning",
        {"micro_batch_ms": float(wait_ms)},
        api_key=api_key,
        timeout=timeout,
    )
    if status != 200 or body.get("ok") is not True:
        raise RuntimeError(f"Live tuning failed for micro_batch_ms={wait_ms}: HTTP {status}: {body}")
    return body


def build_payload(mode: str, batch_rows: int) -> bytes:
    contract = MODE_CONTRACTS[mode]
    obs_channels = int(contract["obs_channels"])
    actions = int(contract["actions"])
    obs_row = [[0.0] * 34 for _ in range(obs_channels)]
    masks: list[list[bool]] = []
    obs: list[list[list[float]]] = []
    for row in range(batch_rows):
        mask = [False] * actions
        mask[0 if row % 2 == 0 else actions - 1] = True
        masks.append(mask)
        obs.append(obs_row)
    raw = json.dumps({"obs": obs, "masks": masks}, separators=(",", ":")).encode("utf-8")
    return gzip.compress(raw, compresslevel=1)


def mode_metrics(snapshot: dict[str, Any], mode: str) -> dict[str, Any]:
    return dict(snapshot.get("modes", {}).get(mode, {}) or {})


def metric_delta(before: dict[str, Any], after: dict[str, Any], key: str) -> int:
    return max(0, int(after.get(key, 0) or 0) - int(before.get(key, 0) or 0))


def current_settings(metrics: dict[str, Any]) -> dict[str, Any]:
    micro = metrics.get("micro_batch", {}) or {}
    reload_cfg = metrics.get("reload", {}) or {}
    return {
        "micro_batch_ms": float(micro.get("wait_ms", 1.0) or 0.0),
        "micro_batch_max_rows": int(micro.get("max_rows", 64) or 64),
        "max_pending_requests": int(micro.get("max_pending_requests", 128) or 128),
        "request_deadline_ms": float(micro.get("request_deadline_ms", 3500.0) or 3500.0),
        "reload_poll_ms": float(reload_cfg.get("poll_ms", 500.0) or 500.0),
    }


def recommend(
    settings: dict[str, Any],
    mode_results: dict[str, dict[str, Any]],
    *,
    concurrency: int,
    batch_rows: int,
) -> dict[str, Any]:
    recommendation = dict(settings)
    reasons: list[str] = []
    failure = any(float(result.get("error_rate", 0.0)) > 0.0 for result in mode_results.values())
    p95_values = [
        float(result["latency_ms"]["p95"])
        for result in mode_results.values()
        if result.get("latency_ms", {}).get("p95") is not None
    ]
    p95 = max(p95_values) if p95_values else math.inf
    batch_values = [
        float(result.get("observed_rows_per_execution", 0.0))
        for result in mode_results.values()
        if result.get("observed_rows_per_execution") is not None
    ]
    observed_batch = min(batch_values) if batch_values else 0.0
    current_wait = float(settings["micro_batch_ms"])

    if failure or p95 >= 250.0:
        recommendation["micro_batch_ms"] = max(0.0, round(current_wait - 0.5, 2))
        reasons.append("오류/고지연을 감지해 micro-batch 대기시간을 줄였습니다.")
    elif concurrency >= 4 and p95 < 80.0 and observed_batch < max(2.0, min(8.0, concurrency * batch_rows / 2.0)):
        recommendation["micro_batch_ms"] = min(2.0, round(current_wait + 0.5, 2))
        reasons.append("지연 여유가 크고 GPU batch 결합률이 낮아 micro-batch 대기시간을 소폭 늘렸습니다.")
    else:
        reasons.append("현재 micro-batch 대기시간이 latency/결합률 균형 범위에 있습니다.")

    target_rows = max(64, min(256, 2 ** math.ceil(math.log2(max(1, concurrency * batch_rows * 2)))))
    recommendation["micro_batch_max_rows"] = max(int(settings["micro_batch_max_rows"]), target_rows)

    if any(int(result.get("busy_rejections", 0)) > 0 for result in mode_results.values()):
        recommendation["max_pending_requests"] = min(512, max(int(settings["max_pending_requests"]) * 2, concurrency * 8))
        reasons.append("queue busy rejection이 발생해 pending 한도를 늘렸습니다.")
    else:
        recommendation["max_pending_requests"] = max(int(settings["max_pending_requests"]), concurrency * 4)

    recommendation["request_deadline_ms"] = min(3500.0, float(settings["request_deadline_ms"]))
    recommendation["reload_poll_ms"] = float(settings["reload_poll_ms"])
    return {
        "kind": "heuristic",
        "requires_ab_validation": True,
        "recommended": recommendation,
        "reasons": reasons,
    }


def run_mode(
    server: str,
    api_key: str,
    mode: str,
    *,
    requests: int,
    concurrency: int,
    batch_rows: int,
    timeout: float,
) -> dict[str, Any]:
    endpoint = str(MODE_CONTRACTS[mode]["endpoint"])
    payload = build_payload(mode, batch_rows)

    for _ in range(2):
        status, _, _ = request_json(f"{server}{endpoint}", api_key=api_key, body=payload, timeout=timeout)
        if status != 200:
            raise RuntimeError(f"{mode} warmup failed with HTTP {status}")

    metrics_status, before_metrics, _ = request_json(
        f"{server}/api/inference/metrics", api_key=api_key, timeout=timeout
    )
    if metrics_status != 200:
        raise RuntimeError(f"{mode} could not read baseline server metrics: HTTP {metrics_status}")

    latencies: list[float] = []
    statuses: dict[str, int] = {}
    successful = 0
    started = time.perf_counter()

    def one() -> tuple[int, float]:
        status, body, latency = request_json(f"{server}{endpoint}", api_key=api_key, body=payload, timeout=timeout)
        if status == 200:
            actions = body.get("actions")
            if not isinstance(actions, list) or len(actions) != batch_rows:
                raise RuntimeError(f"{mode} response actions shape mismatch")
        return status, latency

    with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix=f"mortal-rogs-bench-{mode}") as pool:
        futures = [pool.submit(one) for _ in range(requests)]
        for future in as_completed(futures):
            try:
                status, latency = future.result()
            except Exception:
                statuses["client_error"] = statuses.get("client_error", 0) + 1
                continue
            statuses[str(status)] = statuses.get(str(status), 0) + 1
            latencies.append(latency)
            if status == 200:
                successful += 1

    elapsed = max(time.perf_counter() - started, 1.0e-9)
    _, metrics_after, _ = request_json(f"{server}/api/inference/metrics", api_key=api_key, timeout=timeout)
    before_mode = mode_metrics(before_metrics, mode)
    after_mode = mode_metrics(metrics_after, mode)
    executions = metric_delta(before_mode, after_mode, "executions_total")
    coalesced = metric_delta(before_mode, after_mode, "coalesced_requests_total")
    busy = metric_delta(before_mode, after_mode, "busy_rejections_total")
    timeouts = metric_delta(before_mode, after_mode, "timeouts_total")
    successful_rows = successful * batch_rows

    return {
        "mode": mode,
        "endpoint": endpoint,
        "requests": requests,
        "concurrency": concurrency,
        "batch_rows": batch_rows,
        "successful_requests": successful,
        "error_rate": round((requests - successful) / requests, 6),
        "status_counts": statuses,
        "elapsed_s": round(elapsed, 3),
        "requests_per_s": round(successful / elapsed, 3),
        "rows_per_s": round(successful_rows / elapsed, 3),
        "latency_ms": latency_summary(latencies),
        "server_delta": {
            "executions": executions,
            "coalesced_requests": coalesced,
            "busy_rejections": busy,
            "timeouts": timeouts,
        },
        "observed_rows_per_execution": round(successful_rows / executions, 3) if executions else None,
        "busy_rejections": busy,
        "timeouts": timeouts,
        "server_after": after_mode,
    }


def parse_modes(value: str) -> list[str]:
    normalized = value.strip().casefold()
    if normalized in {"both", "all", "3p+4p"}:
        return ["3p", "4p"]
    if normalized in MODE_CONTRACTS:
        return [normalized]
    raise argparse.ArgumentTypeError("modes must be 3p, 4p or both")


def parse_sweep_waits(value: str) -> list[float]:
    waits: list[float] = []
    seen: set[float] = set()
    for part in value.split(","):
        text = part.strip()
        if not text:
            continue
        try:
            wait = round(float(text), 3)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"invalid sweep wait: {text}") from exc
        if not 0.0 <= wait <= 100.0:
            raise argparse.ArgumentTypeError("sweep waits must be between 0 and 100 ms")
        if wait not in seen:
            waits.append(wait)
            seen.add(wait)
    if not waits:
        raise argparse.ArgumentTypeError("sweep waits must contain at least one value")
    return waits


def summarize_candidate(wait_ms: float, results: dict[str, dict[str, Any]], latency_budget_ms: float) -> dict[str, Any]:
    p95_values = [
        float(result["latency_ms"]["p95"])
        for result in results.values()
        if result.get("latency_ms", {}).get("p95") is not None
    ]
    max_p95 = max(p95_values) if p95_values else math.inf
    throughput = sum(float(result.get("rows_per_s", 0.0)) for result in results.values())
    failed_requests = sum(int(result["requests"] - result["successful_requests"]) for result in results.values())
    busy = sum(int(result.get("busy_rejections", 0)) for result in results.values())
    timeouts = sum(int(result.get("timeouts", 0)) for result in results.values())
    safe = failed_requests == 0 and busy == 0 and timeouts == 0 and math.isfinite(max_p95)
    return {
        "micro_batch_ms": wait_ms,
        "modes": results,
        "aggregate": {
            "rows_per_s": round(throughput, 3),
            "max_p95_ms": round(max_p95, 3) if math.isfinite(max_p95) else None,
            "failed_requests": failed_requests,
            "busy_rejections": busy,
            "timeouts": timeouts,
            "safe": safe,
            "within_latency_budget": bool(safe and max_p95 <= latency_budget_ms),
        },
    }


def select_sweep_winner(candidates: list[dict[str, Any]], latency_budget_ms: float) -> dict[str, Any]:
    if not candidates:
        raise ValueError("sweep requires at least one candidate")
    within = [candidate for candidate in candidates if candidate["aggregate"]["within_latency_budget"]]
    if within:
        return max(
            within,
            key=lambda candidate: (
                float(candidate["aggregate"]["rows_per_s"]),
                -float(candidate["aggregate"]["max_p95_ms"]),
            ),
        )
    safe = [candidate for candidate in candidates if candidate["aggregate"]["safe"]]
    if safe:
        return min(
            safe,
            key=lambda candidate: (
                float(candidate["aggregate"]["max_p95_ms"]),
                -float(candidate["aggregate"]["rows_per_s"]),
            ),
        )
    return min(
        candidates,
        key=lambda candidate: (
            int(candidate["aggregate"]["failed_requests"]),
            int(candidate["aggregate"]["busy_rejections"]),
            int(candidate["aggregate"]["timeouts"]),
            float(candidate["aggregate"]["max_p95_ms"] or math.inf),
        ),
    )


def run_sweep(
    server: str,
    api_key: str,
    modes: list[str],
    settings: dict[str, Any],
    waits: list[float],
    *,
    requests: int,
    concurrency: int,
    batch_rows: int,
    timeout: float,
    latency_budget_ms: float,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    original_wait = float(settings["micro_batch_ms"])
    candidates: list[dict[str, Any]] = []
    restored = False
    restore_error: str | None = None
    try:
        for wait_ms in waits:
            apply_micro_batch_wait(server, api_key, wait_ms, timeout)
            time.sleep(0.05)
            results: dict[str, dict[str, Any]] = {}
            for mode in modes:
                results[mode] = run_mode(
                    server,
                    api_key,
                    mode,
                    requests=requests,
                    concurrency=concurrency,
                    batch_rows=batch_rows,
                    timeout=timeout,
                )
            candidates.append(summarize_candidate(wait_ms, results, latency_budget_ms))
    finally:
        try:
            apply_micro_batch_wait(server, api_key, original_wait, timeout)
            restored = True
        except Exception as exc:
            restore_error = f"{type(exc).__name__}: {exc}"

    winner = select_sweep_winner(candidates, latency_budget_ms)
    recommendation = dict(settings)
    recommendation["micro_batch_ms"] = float(winner["micro_batch_ms"])
    sweep = {
        "kind": "measured_ab_sweep",
        "latency_budget_ms": latency_budget_ms,
        "candidates": candidates,
        "winner_micro_batch_ms": winner["micro_batch_ms"],
        "winner_aggregate": winner["aggregate"],
        "original_micro_batch_ms": original_wait,
        "original_restored": restored,
        "restore_error": restore_error,
    }
    recommendation_report = {
        "kind": "measured_ab_sweep",
        "requires_ab_validation": False,
        "requires_live_game_validation": True,
        "recommended": recommendation,
        "reasons": [
            f"동일 loaded model에서 {len(candidates)}개 micro-batch wait 후보를 실측했습니다.",
            f"latency budget {latency_budget_ms:g}ms 내에서는 합산 rows/s가 가장 높은 후보를 선택합니다.",
            "후보 측정 후 원래 live scheduler 값을 복구합니다.",
        ],
    }
    return sweep, recommendation_report, dict(winner["modes"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark the live Mortal-ROGS Akagi inference API.")
    parser.add_argument("--server", default="http://127.0.0.1:8190")
    parser.add_argument("--api-key", default=os.getenv("MORTAL_INFERENCE_API_KEY", ""))
    parser.add_argument("--modes", default="both")
    parser.add_argument("--requests", type=int, default=64)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--batch-rows", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=4.0)
    parser.add_argument("--sweep-waits", default="")
    parser.add_argument("--latency-budget-ms", type=float, default=100.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    modes = parse_modes(args.modes)
    if args.requests < 1:
        raise SystemExit("--requests must be >= 1")
    if args.concurrency < 1:
        raise SystemExit("--concurrency must be >= 1")
    if args.batch_rows < 1:
        raise SystemExit("--batch-rows must be >= 1")
    if args.timeout <= 0:
        raise SystemExit("--timeout must be > 0")
    if args.latency_budget_ms <= 0:
        raise SystemExit("--latency-budget-ms must be > 0")

    server = args.server.rstrip("/")
    status, health, _ = request_json(f"{server}/health", api_key=args.api_key, timeout=args.timeout)
    if status != 200 or health.get("protocol") != "akagiot-v1":
        raise SystemExit(f"Mortal inference API is not healthy: HTTP {status}: {health}")

    status, before_metrics, _ = request_json(f"{server}/api/inference/metrics", api_key=args.api_key, timeout=args.timeout)
    if status != 200 or before_metrics.get("protocol") != "mortal-rogs-inference-v1":
        raise SystemExit(f"Managed metrics endpoint unavailable: HTTP {status}: {before_metrics}")

    settings = current_settings(before_metrics)
    sweep = None
    if args.sweep_waits.strip():
        waits = parse_sweep_waits(args.sweep_waits)
        sweep, recommendation_report, results = run_sweep(
            server,
            args.api_key,
            modes,
            settings,
            waits,
            requests=args.requests,
            concurrency=args.concurrency,
            batch_rows=args.batch_rows,
            timeout=args.timeout,
            latency_budget_ms=args.latency_budget_ms,
        )
    else:
        results: dict[str, dict[str, Any]] = {}
        for mode in modes:
            results[mode] = run_mode(
                server,
                args.api_key,
                mode,
                requests=args.requests,
                concurrency=args.concurrency,
                batch_rows=args.batch_rows,
                timeout=args.timeout,
            )
        recommendation_report = recommend(settings, results, concurrency=args.concurrency, batch_rows=args.batch_rows)

    report = {
        "protocol": "mortal-rogs-serving-benchmark-v1",
        "server": server,
        "health": {
            "degraded": bool(health.get("degraded")),
            "models": health.get("models", {}),
        },
        "settings": settings,
        "workload": {
            "modes": modes,
            "requests_per_mode": args.requests,
            "concurrency": args.concurrency,
            "batch_rows": args.batch_rows,
            "gzip": True,
        },
        "modes": results,
        "sweep": sweep,
        "recommendation": recommendation_report,
    }

    if args.output is not None:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["output"] = str(output)

    if sweep is not None:
        print("MORTAL_INFERENCE_SWEEP_OK")
    print("MORTAL_INFERENCE_BENCHMARK_OK")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
