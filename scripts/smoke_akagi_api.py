from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def request_json(
    url: str,
    *,
    api_key: str = "",
    payload: dict | None = None,
    gzip_body: bool = False,
    timeout: float = 15.0,
) -> tuple[int, dict]:
    data = None
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = api_key
    if payload is not None:
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        if gzip_body:
            raw = gzip.compress(raw)
            headers["Content-Encoding"] = "gzip"
        headers["Content-Type"] = "application/json"
        data = raw
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.status), json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8")
        except OSError as body_exc:
            # On Windows an endpoint that rejects a POST before consuming its
            # request body can close/reset the body stream after the HTTP status
            # has already been received. Preserve the authoritative status code;
            # later successful requests still verify that the server stayed alive.
            return int(exc.code), {
                "raw": "",
                "body_read_error": f"{type(body_exc).__name__}: {body_exc}",
            }
        try:
            decoded = json.loads(body)
        except json.JSONDecodeError:
            decoded = {"raw": body}
        return int(exc.code), decoded


def touch_new_signature(path: Path) -> None:
    now = time.time_ns()
    os.utime(path, ns=(now, now))


def build_payload(obs_channels: int, actions: int, *, batch: int = 2) -> tuple[dict, list[int]]:
    if batch < 1:
        raise ValueError("batch must be >= 1")
    expected = [0 if index % 2 == 0 else actions - 1 for index in range(batch)]
    masks: list[list[bool]] = []
    for action in expected:
        row = [False] * actions
        row[action] = True
        masks.append(row)
    return {
        "obs": [[[0.0] * 34 for _ in range(obs_channels)] for _ in range(batch)],
        "masks": masks,
    }, expected


def assert_mode_response(mode: str, body: dict, *, actions: int, expected_actions: list[int]) -> None:
    if body.get("actions") != expected_actions:
        raise SystemExit(f"{mode} API selected illegal/unexpected actions: {body.get('actions')} vs {expected_actions}")
    batch = len(expected_actions)
    if len(body.get("q_out", [])) != batch or any(len(row) != actions for row in body["q_out"]):
        raise SystemExit(f"{mode} API q_out shape mismatch")
    if len(body.get("masks", [])) != batch or any(len(row) != actions for row in body["masks"]):
        raise SystemExit(f"{mode} API mask shape mismatch")
    if body.get("is_greedy") != [True] * batch:
        raise SystemExit(f"{mode} API greedy flags mismatch: {body.get('is_greedy')}")
    for row_index, legal_action in enumerate(expected_actions):
        for action_index, value in enumerate(body["q_out"][row_index]):
            if action_index != legal_action and value > -1.0e8:
                raise SystemExit(f"{mode} API did not sanitize illegal Q value at row={row_index} action={action_index}")


def assert_managed_response(mode: str, body: dict, *, actions: int, obs_channels: int) -> None:
    if body.get("protocol") != "mortal-rogs-inference-v1":
        raise SystemExit(f"{mode} managed API protocol mismatch: {body}")
    if body.get("mode") != mode or body.get("action_space") != actions:
        raise SystemExit(f"{mode} managed API mode/action metadata mismatch: {body}")
    if body.get("obs_shape") != [obs_channels, 34]:
        raise SystemExit(f"{mode} managed API obs metadata mismatch: {body.get('obs_shape')}")
    latency = body.get("latency_ms")
    if not isinstance(latency, (int, float)) or latency < 0:
        raise SystemExit(f"{mode} managed API latency metadata invalid: {latency}")
    model = body.get("model")
    if not isinstance(model, dict) or model.get("abi_version") != 4 or not model.get("checkpoint_signature"):
        raise SystemExit(f"{mode} managed API model identity invalid: {model}")
    if model.get("current") is not True:
        raise SystemExit(f"{mode} managed API reported a stale model: {model}")


def wait_ready(proc: subprocess.Popen[str], base: str, api_key: str) -> dict:
    deadline = time.time() + 180
    while time.time() < deadline:
        if proc.poll() is not None:
            output = proc.stdout.read() if proc.stdout else ""
            raise SystemExit(f"Inference API exited before readiness ({proc.returncode}):\n{output}")
        try:
            status, health = request_json(f"{base}/health", api_key=api_key)
            if status == 200:
                return health
        except OSError:
            pass
        time.sleep(0.25)
    raise SystemExit("Inference API did not become ready after prewarm")


def wait_model_state(base: str, api_key: str, mode: str, predicate, *, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    latest: dict = {}
    while time.time() < deadline:
        status, latest = request_json(f"{base}/health", api_key=api_key)
        if status == 200 and predicate(latest, latest.get("models", {}).get(mode, {})):
            return latest
        time.sleep(0.05)
    raise SystemExit(f"Timed out waiting for {mode} model state: {latest}")


def main() -> int:
    p = argparse.ArgumentParser(description="End-to-end smoke for the Akagi-NG-compatible Mortal inference HTTP API")
    p.add_argument("--runtime-root", type=Path, required=True)
    p.add_argument("--device", default="cpu")
    p.add_argument("--model-3p", type=Path)
    p.add_argument("--model-4p", type=Path)
    p.add_argument("--api-key", default="mortal-rogs-smoke-key")
    args = p.parse_args()

    project = Path(__file__).resolve().parents[1]
    root = args.runtime_root.expanduser().resolve()
    smoke_3p = root / "runtime" / "smoke-training" / "smoke-trained-3p.pth"
    smoke_4p = root / "runtime" / "smoke-training" / "smoke-trained-4p.pth"
    source_3p = args.model_3p.resolve() if args.model_3p else smoke_3p.resolve() if smoke_3p.is_file() else None
    source_4p = args.model_4p.resolve() if args.model_4p else smoke_4p.resolve() if smoke_4p.is_file() else None
    for path in (source_3p, source_4p):
        if path is None or not path.is_file():
            raise SystemExit(f"API smoke checkpoint missing: {path}")

    api_root = root / "runtime" / "smoke-api"
    if api_root.exists():
        shutil.rmtree(api_root)
    api_root.mkdir(parents=True, exist_ok=True)
    model_3p = api_root / "api-3p.pth"
    model_4p = api_root / "api-4p.pth"
    shutil.copyfile(source_3p, model_3p)
    shutil.copyfile(source_4p, model_4p)
    touch_new_signature(model_3p)
    touch_new_signature(model_4p)

    port = free_port()
    base = f"http://127.0.0.1:{port}"
    server = project / "scripts" / "serve_akagi_api.py"
    cmd = [
        sys.executable,
        str(server),
        "--runtime-root",
        str(root),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--device",
        args.device,
        "--api-key",
        args.api_key,
        "--model-3p",
        str(model_3p),
        "--model-4p",
        str(model_4p),
        "--micro-batch-ms",
        "20",
        "--micro-batch-max-rows",
        "64",
        "--max-pending-requests",
        "64",
        "--request-deadline-ms",
        "3500",
        "--reload-poll-ms",
        "100",
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(project), str(root / "mortal"), env.get("PYTHONPATH", "")]).rstrip(
        os.pathsep
    )
    proc = subprocess.Popen(
        cmd,
        cwd=project,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        health = wait_ready(proc, base, args.api_key)
        if health.get("protocol") != "akagiot-v1" or health.get("degraded"):
            raise SystemExit(f"Unexpected prewarmed health: {health}")
        for mode in ("3p", "4p"):
            info = health["models"][mode]
            if not info["loaded"] or not info["current"] or info["last_error"] is not None:
                raise SystemExit(f"{mode} was not prewarmed before HTTP readiness: {info}")

        bad_health, _ = request_json(f"{base}/health", api_key="wrong-key")
        if bad_health != 401:
            raise SystemExit(f"Protected health endpoint should return 401, got {bad_health}")
        bad_models, _ = request_json(f"{base}/api/inference/models", api_key="wrong-key")
        if bad_models != 401:
            raise SystemExit(f"Protected managed endpoint should return 401, got {bad_models}")

        managed_health_status, managed_health = request_json(f"{base}/api/inference/health", api_key=args.api_key)
        if managed_health_status != 200 or managed_health.get("management_protocol") != "mortal-rogs-inference-v1":
            raise SystemExit(f"Managed health contract failed: HTTP {managed_health_status}: {managed_health}")
        models_status, models_body = request_json(f"{base}/api/inference/models", api_key=args.api_key)
        if models_status != 200 or models_body.get("protocol") != "mortal-rogs-inference-v1":
            raise SystemExit(f"Managed models contract failed: HTTP {models_status}: {models_body}")

        wrong_shape_status, _ = request_json(
            f"{base}/react_batch_3p",
            api_key=args.api_key,
            payload=build_payload(1012, 46)[0],
            gzip_body=True,
        )
        if wrong_shape_status != 400:
            raise SystemExit(f"4P-shaped payload on 3P endpoint should return 400, got {wrong_shape_status}")
        # Unsupported-mode validation happens before the request body is read.
        # A tiny POST avoids Windows TCP reset behavior from a large unread body.
        bad_mode_status, _ = request_json(f"{base}/api/inference/5p", api_key=args.api_key, payload={})
        if bad_mode_status != 404:
            raise SystemExit(f"Unsupported managed mode should return 404, got {bad_mode_status}")

        results: dict[str, object] = {"health": health, "managed_health": managed_health, "modes": {}}
        mode_payloads: dict[str, tuple[str, dict, list[int], int]] = {}
        for mode, endpoint, obs_channels, actions in (
            ("3p", "/react_batch_3p", 1010, 44),
            ("4p", "/react_batch", 1012, 46),
        ):
            payload, expected_actions = build_payload(obs_channels, actions)
            mode_payloads[mode] = (endpoint, payload, expected_actions, actions)
            status, body = request_json(f"{base}{endpoint}", api_key=args.api_key, payload=payload, gzip_body=True)
            if status != 200:
                raise SystemExit(f"{mode} API returned HTTP {status}: {body}")
            assert_mode_response(mode, body, actions=actions, expected_actions=expected_actions)

            managed_status, managed_body = request_json(
                f"{base}/api/inference/{mode}", api_key=args.api_key, payload=payload, gzip_body=True
            )
            if managed_status != 200:
                raise SystemExit(f"{mode} managed API returned HTTP {managed_status}: {managed_body}")
            assert_mode_response(f"{mode}-managed", managed_body, actions=actions, expected_actions=expected_actions)
            assert_managed_response(mode, managed_body, actions=actions, obs_channels=obs_channels)
            results["modes"][mode] = {
                "endpoint": endpoint,
                "managed_endpoint": f"/api/inference/{mode}",
                "batch": len(expected_actions),
                "obs": [obs_channels, 34],
                "action_space": actions,
                "actions": body["actions"],
                "latency_ms": managed_body["latency_ms"],
                "model": managed_body["model"],
            }

        payload, expected = build_payload(1010, 44, batch=1)
        barrier = threading.Barrier(7)

        def concurrent_call(_: int) -> tuple[int, dict]:
            barrier.wait()
            return request_json(
                f"{base}/react_batch_3p",
                api_key=args.api_key,
                payload=payload,
                gzip_body=True,
                timeout=5,
            )

        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(concurrent_call, index) for index in range(6)]
            barrier.wait()
            concurrent_results = [future.result(timeout=8) for future in futures]
        for status, body in concurrent_results:
            if status != 200:
                raise SystemExit(f"Concurrent 3P inference failed HTTP {status}: {body}")
            assert_mode_response("3p-concurrent", body, actions=44, expected_actions=expected)

        metrics_status, metrics = request_json(f"{base}/api/inference/metrics", api_key=args.api_key)
        if metrics_status != 200 or metrics.get("protocol") != "mortal-rogs-inference-v1":
            raise SystemExit(f"Inference metrics endpoint failed: HTTP {metrics_status}: {metrics}")
        config = metrics.get("micro_batch", {})
        if config.get("request_deadline_ms") != 3500.0 or config.get("wait_ms") != 20.0:
            raise SystemExit(f"Inference scheduling config mismatch: {config}")
        m3 = metrics.get("modes", {}).get("3p", {})
        if m3.get("requests_total", 0) < 8 or m3.get("rows_total", 0) < 9:
            raise SystemExit(f"3P inference metrics counters too small: {m3}")
        if m3.get("coalesced_requests_total", 0) < 1 or m3.get("max_rows_per_execution", 0) < 2:
            raise SystemExit(f"Concurrent requests were not micro-batched: {m3}")
        if m3.get("latency_ms", {}).get("request", {}).get("p95") is None:
            raise SystemExit(f"3P latency percentile telemetry missing: {m3}")

        signatures_before_tuning = {mode: health["models"][mode]["loaded_signature"] for mode in ("3p", "4p")}
        bad_tuning_status, _ = request_json(
            f"{base}/api/inference/tuning", api_key="wrong-key", payload={"micro_batch_ms": 5}
        )
        if bad_tuning_status != 401:
            raise SystemExit(f"Live tuning must require auth, got HTTP {bad_tuning_status}")
        unsupported_tuning_status, _ = request_json(
            f"{base}/api/inference/tuning", api_key=args.api_key, payload={"request_deadline_ms": 1000}
        )
        if unsupported_tuning_status != 400:
            raise SystemExit(f"Live tuning must reject non-wait fields, got HTTP {unsupported_tuning_status}")
        tuning_status, tuning_body = request_json(
            f"{base}/api/inference/tuning", api_key=args.api_key, payload={"micro_batch_ms": 5}
        )
        if tuning_status != 200 or tuning_body.get("models_reloaded") is not False:
            raise SystemExit(f"Live micro-batch tuning failed: HTTP {tuning_status}: {tuning_body}")
        _, tuned_health = request_json(f"{base}/health", api_key=args.api_key)
        if tuned_health.get("serving", {}).get("micro_batch", {}).get("wait_ms") != 5.0:
            raise SystemExit(f"Live tuning was not reflected in health: {tuned_health}")
        for mode in ("3p", "4p"):
            if tuned_health["models"][mode]["loaded_signature"] != signatures_before_tuning[mode]:
                raise SystemExit(f"{mode} model changed during scheduler-only tuning: {tuned_health['models'][mode]}")
        restore_tuning_status, _ = request_json(
            f"{base}/api/inference/tuning", api_key=args.api_key, payload={"micro_batch_ms": 20}
        )
        if restore_tuning_status != 200:
            raise SystemExit(f"Could not restore live tuning to 20ms: HTTP {restore_tuning_status}")

        sweep_report_path = api_root / "sweep-report.json"
        sweep_env = env.copy()
        sweep_env["MORTAL_INFERENCE_API_KEY"] = args.api_key
        sweep_cmd = [
            sys.executable,
            str(project / "scripts" / "benchmark_inference_api.py"),
            "--server",
            base,
            "--modes",
            "3p",
            "--requests",
            "4",
            "--concurrency",
            "2",
            "--batch-rows",
            "1",
            "--sweep-waits",
            "0,1",
            "--latency-budget-ms",
            "1000",
            "--output",
            str(sweep_report_path),
        ]
        sweep_proc = subprocess.run(
            sweep_cmd,
            cwd=project,
            env=sweep_env,
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
        )
        if sweep_proc.returncode != 0:
            raise SystemExit(
                f"Inference A/B sweep failed ({sweep_proc.returncode}):\n{sweep_proc.stdout}\n{sweep_proc.stderr}"
            )
        if "MORTAL_INFERENCE_SWEEP_OK" not in sweep_proc.stdout or not sweep_report_path.is_file():
            raise SystemExit(f"Inference sweep marker/report missing:\n{sweep_proc.stdout}")
        sweep_report = json.loads(sweep_report_path.read_text(encoding="utf-8"))
        sweep = sweep_report.get("sweep", {})
        if sweep.get("original_restored") is not True or len(sweep.get("candidates", [])) != 2:
            raise SystemExit(f"Inference sweep did not restore/measure both candidates: {sweep}")
        if sweep_report.get("recommendation", {}).get("kind") != "measured_ab_sweep":
            raise SystemExit(f"Inference sweep recommendation type mismatch: {sweep_report.get('recommendation')}")
        _, after_sweep_health = request_json(f"{base}/health", api_key=args.api_key)
        if after_sweep_health.get("serving", {}).get("micro_batch", {}).get("wait_ms") != 20.0:
            raise SystemExit(f"Inference sweep did not restore 20ms wait: {after_sweep_health}")
        for mode in ("3p", "4p"):
            if after_sweep_health["models"][mode]["loaded_signature"] != signatures_before_tuning[mode]:
                raise SystemExit(f"{mode} model changed during A/B sweep: {after_sweep_health['models'][mode]}")

        reload_status, reload_body = request_json(
            f"{base}/api/inference/reload", api_key=args.api_key, payload={"mode": "3p"}
        )
        if reload_status != 200 or reload_body.get("results", {}).get("3p", {}).get("ok") is not True:
            raise SystemExit(f"Explicit 3P reload contract failed: HTTP {reload_status}: {reload_body}")

        _, loaded_health = request_json(f"{base}/health", api_key=args.api_key)
        cuda_expected = args.device.strip().casefold().startswith("cuda")
        for mode in ("3p", "4p"):
            info = loaded_health["models"][mode]
            if not info["loaded"] or not info["current"] or info["last_error"] is not None:
                raise SystemExit(f"{mode} model did not remain current after load: {info}")
            if cuda_expected:
                if info.get("compiled") is not True or info.get("amp_dtype") != "bfloat16":
                    raise SystemExit(f"{mode} CUDA API model did not use compile+BF16: {info}")

        shutil.copyfile(source_4p, model_3p)
        touch_new_signature(model_3p)
        endpoint, payload, expected_actions, actions = mode_payloads["3p"]
        status, body = request_json(f"{base}{endpoint}", api_key=args.api_key, payload=payload, gzip_body=True)
        if status != 200:
            raise SystemExit(f"3P background-reload fallback should keep serving, got HTTP {status}: {body}")
        assert_mode_response("3p-background-reload-fallback", body, actions=actions, expected_actions=expected_actions)

        rejected_reload_status, rejected_reload = request_json(
            f"{base}/api/inference/reload", api_key=args.api_key, payload={"mode": "3p"}
        )
        if rejected_reload_status != 409:
            raise SystemExit(
                f"Explicit reload must reject a bad candidate without dropping old model, got "
                f"HTTP {rejected_reload_status}: {rejected_reload}"
            )
        degraded_health = wait_model_state(
            base,
            args.api_key,
            "3p",
            lambda health_state, info: bool(health_state.get("degraded") and not info.get("current") and info.get("last_error")),
        )
        if "does not match endpoint 3p" not in degraded_health["models"]["3p"]["last_error"]:
            raise SystemExit(f"Unexpected 3P candidate rejection: {degraded_health['models']['3p']}")

        shutil.copyfile(source_3p, model_3p)
        touch_new_signature(model_3p)
        recovered_health = wait_model_state(
            base,
            args.api_key,
            "3p",
            lambda health_state, info: bool(not health_state.get("degraded") and info.get("current") and not info.get("last_error")),
            timeout=30,
        )
        status, body = request_json(f"{base}{endpoint}", api_key=args.api_key, payload=payload, gzip_body=True)
        if status != 200:
            raise SystemExit(f"3P background hot-reload recovery inference failed HTTP {status}: {body}")
        assert_mode_response("3p-background-reload-recovery", body, actions=actions, expected_actions=expected_actions)

        results["prewarm"] = {"ready_only_after_models_loaded": True, "health_requires_auth": True}
        results["performance"] = {
            "device": args.device,
            "cuda_compile_required": cuda_expected,
            "compiled": {mode: loaded_health["models"][mode].get("compiled") for mode in ("3p", "4p")},
            "amp_dtype": {mode: loaded_health["models"][mode].get("amp_dtype") for mode in ("3p", "4p")},
        }
        results["managed_api"] = {
            "protocol": "mortal-rogs-inference-v1",
            "health": True,
            "models": True,
            "metrics": True,
            "live_tuning": True,
            "batch_inference": True,
            "latency_percentiles": True,
            "explicit_reload": True,
        }
        results["scheduling"] = {
            "micro_batch": True,
            "coalesced_requests": m3["coalesced_requests_total"],
            "max_rows_per_execution": m3["max_rows_per_execution"],
            "request_deadline_ms": config["request_deadline_ms"],
            "akagi_read_timeout_ms": 4000,
            "live_tuning_without_model_reload": True,
            "ab_sweep_candidates": len(sweep["candidates"]),
            "ab_sweep_original_restored": sweep["original_restored"],
        }
        results["hot_reload"] = {
            "wrong_mode_rejected": True,
            "old_model_kept_serving": True,
            "health_degraded_on_reject": True,
            "background_recovery": recovered_health["models"]["3p"]["current"],
        }
        print("MORTAL_MANAGED_INFERENCE_API_OK")
        print("MORTAL_INFERENCE_MICROBATCH_OK")
        print("MORTAL_INFERENCE_TELEMETRY_OK")
        print("MORTAL_INFERENCE_LIVE_TUNING_OK")
        print("MORTAL_INFERENCE_SWEEP_E2E_OK")
        print("MORTAL_INFERENCE_BACKGROUND_RELOAD_OK")
        print("MORTAL_AKAGI_API_PREWARM_OK")
        print("MORTAL_AKAGI_API_PERFORMANCE_OK")
        print("MORTAL_AKAGI_API_HOT_RELOAD_OK")
        print("MORTAL_AKAGI_API_E2E_OK")
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        if proc.stdout:
            tail = proc.stdout.read().strip()
            if tail:
                print("--- inference-api output ---")
                print(tail[-5000:])


if __name__ == "__main__":
    raise SystemExit(main())