from __future__ import annotations

import argparse
import gzip
import json
import os
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
            raw = gzip.compress(raw, compresslevel=1)
            headers["Content-Encoding"] = "gzip"
        headers["Content-Type"] = "application/json"
        data = raw
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return int(response.status), json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"raw": raw}
        return int(exc.code), body


def build_payload(channels: int, actions: int) -> tuple[dict, int]:
    legal = actions - 1
    mask = [False] * actions
    mask[legal] = True
    return {
        "obs": [[[0.0] * 34 for _ in range(channels)]],
        "masks": [mask],
    }, legal


def wait_ready(proc: subprocess.Popen[str], base: str, api_key: str) -> dict:
    deadline = time.time() + 180.0
    while time.time() < deadline:
        if proc.poll() is not None:
            output = proc.stdout.read() if proc.stdout else ""
            raise SystemExit(f"coordination server exited before readiness ({proc.returncode}):\n{output}")
        try:
            status, body = request_json(f"{base}/health", api_key=api_key, timeout=2.0)
            if status == 200:
                return body
        except OSError:
            pass
        time.sleep(0.25)
    raise SystemExit("coordination server did not become ready")


def main() -> int:
    parser = argparse.ArgumentParser(description="Real checkpoint E2E for shared-device coordination and graceful drain")
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--api-key", default="mortal-rogs-coordination-smoke")
    args = parser.parse_args()

    project = Path(__file__).resolve().parents[1]
    root = args.runtime_root.expanduser().resolve()
    model_3p = root / "runtime" / "smoke-training" / "smoke-trained-3p.pth"
    model_4p = root / "runtime" / "smoke-training" / "smoke-trained-4p.pth"
    for model in (model_3p, model_4p):
        if not model.is_file():
            raise SystemExit(f"coordination smoke checkpoint missing: {model}")

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
        "0",
        "--max-device-executions",
        "1",
        "--reload-quiet-ms",
        "10",
        "--reload-wait-ms",
        "500",
        "--drain-timeout-ms",
        "3500",
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(project), str(root / "mortal"), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
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
        lifecycle = health.get("lifecycle", {})
        if lifecycle.get("state") != "running" or lifecycle.get("accepting") is not True:
            raise SystemExit(f"unexpected initial lifecycle: {lifecycle}")
        scheduler = health.get("serving", {}).get("device_scheduler", {})
        if scheduler.get("policy") != "fair-fifo" or scheduler.get("max_parallel_executions") != 1:
            raise SystemExit(f"shared-device scheduler contract mismatch: {scheduler}")

        payload_3p, legal_3p = build_payload(1010, 44)
        payload_4p, legal_4p = build_payload(1012, 46)
        barrier = threading.Barrier(9)

        def mixed_call(index: int) -> tuple[str, int, dict]:
            mode = "3p" if index % 2 == 0 else "4p"
            endpoint = "/react_batch_3p" if mode == "3p" else "/react_batch"
            payload = payload_3p if mode == "3p" else payload_4p
            barrier.wait()
            status, body = request_json(
                f"{base}{endpoint}",
                api_key=args.api_key,
                payload=payload,
                gzip_body=True,
                timeout=5.0,
            )
            return mode, status, body

        with ThreadPoolExecutor(max_workers=8, thread_name_prefix="mortal-rogs-mixed") as pool:
            futures = [pool.submit(mixed_call, index) for index in range(8)]
            barrier.wait()
            mixed = [future.result(timeout=10.0) for future in futures]

        for mode, status, body in mixed:
            expected = legal_3p if mode == "3p" else legal_4p
            if status != 200 or body.get("actions") != [expected]:
                raise SystemExit(f"mixed {mode} request failed: HTTP {status}: {body}")

        metrics_status, metrics = request_json(f"{base}/api/inference/metrics", api_key=args.api_key)
        if metrics_status != 200:
            raise SystemExit(f"coordination metrics failed: HTTP {metrics_status}: {metrics}")
        scheduler = metrics.get("device_scheduler", {})
        if scheduler.get("max_parallel_executions") != 1 or scheduler.get("peak_active_executions") != 1:
            raise SystemExit(f"shared device was not serialized: {scheduler}")
        for mode in ("3p", "4p"):
            if scheduler.get("by_mode", {}).get(mode, {}).get("acquisitions", 0) < 1:
                raise SystemExit(f"shared device did not execute {mode}: {scheduler}")
        if metrics.get("lifecycle", {}).get("inflight_requests") != 0:
            raise SystemExit(f"mixed requests did not settle before drain: {metrics.get('lifecycle')}")

        bad_drain_status, _ = request_json(
            f"{base}/api/inference/drain", api_key="wrong-key", payload={"timeout_ms": 3500}
        )
        if bad_drain_status != 401:
            raise SystemExit(f"drain endpoint must require auth, got HTTP {bad_drain_status}")

        drain_status, drain_body = request_json(
            f"{base}/api/inference/drain", api_key=args.api_key, payload={"timeout_ms": 3500}, timeout=5.0
        )
        drain = drain_body.get("drain", {})
        if drain_status != 200 or drain_body.get("ok") is not True or drain.get("drained") is not True:
            raise SystemExit(f"graceful drain failed: HTTP {drain_status}: {drain_body}")
        if drain.get("state") != "draining" or drain.get("accepting") is not False or drain.get("inflight_requests") != 0:
            raise SystemExit(f"drain lifecycle mismatch: {drain}")

        health_status, drained_health = request_json(f"{base}/health", api_key=args.api_key)
        if health_status != 200 or drained_health.get("lifecycle", {}).get("state") != "draining":
            raise SystemExit(f"health unavailable/incorrect after drain: HTTP {health_status}: {drained_health}")

        rejected_status, rejected_body = request_json(
            f"{base}/react_batch_3p",
            api_key=args.api_key,
            payload=payload_3p,
            gzip_body=True,
            timeout=2.0,
        )
        if rejected_status != 503:
            raise SystemExit(f"new inference after drain must fail fast with 503, got HTTP {rejected_status}: {rejected_body}")

        _, final_metrics = request_json(f"{base}/api/inference/metrics", api_key=args.api_key)
        lifecycle = final_metrics.get("lifecycle", {})
        if lifecycle.get("rejected_during_drain_total", 0) < 1:
            raise SystemExit(f"drain rejection telemetry missing: {lifecycle}")

        print("MORTAL_INFERENCE_DEVICE_COORDINATION_OK")
        print("MORTAL_INFERENCE_MIXED_MODE_OK")
        print("MORTAL_INFERENCE_GRACEFUL_DRAIN_OK")
        print(json.dumps({"device_scheduler": scheduler, "lifecycle": lifecycle}, ensure_ascii=False, indent=2))
        return 0
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5.0)
        if proc.stdout:
            output = proc.stdout.read().strip()
            if output:
                print("--- coordination inference-api output ---")
                print(output[-5000:])


if __name__ == "__main__":
    raise SystemExit(main())
