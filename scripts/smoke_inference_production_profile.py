from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.inference_production import (
    LifecycleOps,
    ProductionApplyError,
    apply_profile_transaction,
    build_profile,
    normalize_serving_settings,
    verify_health,
)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def request_json(
    url: str,
    *,
    api_key: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 5.0,
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
            return int(response.status), json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"raw": raw}
        return int(exc.code), body


def main() -> int:
    parser = argparse.ArgumentParser(description="Real-checkpoint E2E for production serving apply and rollback")
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--api-key", default="mortal-rogs-production-profile-smoke")
    args = parser.parse_args()

    root = args.runtime_root.expanduser().resolve()
    model_3p = root / "runtime" / "smoke-training" / "smoke-trained-3p.pth"
    model_4p = root / "runtime" / "smoke-training" / "smoke-trained-4p.pth"
    for model in (model_3p, model_4p):
        if not model.is_file():
            raise SystemExit(f"production profile smoke checkpoint missing: {model}")

    port = free_port()
    base = f"http://127.0.0.1:{port}"
    profile_dir = root / "runtime" / "smoke-production-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    profile = profile_dir / "production.json"
    try:
        profile.unlink()
    except FileNotFoundError:
        pass

    base_settings = normalize_serving_settings(
        {
            "micro_batch_ms": 0.0,
            "micro_batch_max_rows": 64,
            "max_pending_requests": 64,
            "request_deadline_ms": 3500.0,
            "reload_poll_ms": 500.0,
            "max_device_executions": 1,
            "reload_quiet_ms": 10.0,
            "reload_wait_ms": 500.0,
            "drain_timeout_ms": 3500.0,
        }
    )
    candidate_settings = normalize_serving_settings(
        {
            **base_settings,
            "micro_batch_ms": 1.0,
            "max_pending_requests": 128,
            "reload_quiet_ms": 25.0,
            "reload_wait_ms": 1000.0,
        }
    )
    previous_target = {
        "host": "127.0.0.1",
        "port": port,
        "api_key": args.api_key,
        "device": args.device,
        "serving": base_settings,
    }
    candidate_target = {
        **previous_target,
        "serving": candidate_settings,
    }

    current: dict[str, subprocess.Popen[str] | None] = {"proc": None}
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(PROJECT_ROOT), str(root / "mortal"), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    env["MORTAL_INFERENCE_API_KEY"] = args.api_key

    def command_for(target: dict[str, Any]) -> list[str]:
        serving = normalize_serving_settings(target["serving"])
        return [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "serve_akagi_api.py"),
            "--runtime-root",
            str(root),
            "--host",
            str(target["host"]),
            "--port",
            str(target["port"]),
            "--device",
            str(target["device"]),
            "--model-3p",
            str(model_3p),
            "--model-4p",
            str(model_4p),
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

    def start(target: dict[str, Any]) -> dict[str, Any]:
        proc = current["proc"]
        if proc is not None and proc.poll() is None:
            raise RuntimeError("attempted to start while previous inference process is still running")
        proc = subprocess.Popen(
            command_for(target),
            cwd=PROJECT_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        current["proc"] = proc
        return {"pid": proc.pid, "device": target["device"]}

    def stop() -> dict[str, Any]:
        proc = current["proc"]
        if proc is None:
            return {"stopped": False}
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5.0)
        result = {"stopped": True, "returncode": proc.returncode}
        current["proc"] = None
        return result

    def wait_healthy(target: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_s
        latest: dict[str, Any] = {}
        while time.monotonic() < deadline:
            proc = current["proc"]
            if proc is None:
                raise RuntimeError("inference process is missing")
            if proc.poll() is not None:
                tail = proc.stdout.read()[-3000:] if proc.stdout else ""
                raise RuntimeError(f"inference process exited before readiness ({proc.returncode}): {tail}")
            try:
                status, latest = request_json(f"{base}/health", api_key=args.api_key, timeout=2.0)
                if status == 200 and not verify_health(latest, target["serving"]):
                    return latest
            except OSError:
                pass
            time.sleep(0.1)
        raise RuntimeError(f"inference health timeout: {latest}")

    def drain(timeout_ms: float) -> dict[str, Any]:
        status, body = request_json(
            f"{base}/api/inference/drain",
            api_key=args.api_key,
            payload={"timeout_ms": timeout_ms},
            timeout=max(5.0, timeout_ms / 1000.0 + 2.0),
        )
        if status != 200 or body.get("ok") is not True:
            raise RuntimeError(f"drain failed HTTP {status}: {body}")
        return dict(body.get("drain", {}) or {})

    ops = LifecycleOps(drain=drain, stop=stop, start=start, wait_healthy=wait_healthy)

    try:
        start(previous_target)
        initial_health = wait_healthy(previous_target, 120.0)
        initial_errors = verify_health(initial_health, base_settings)
        if initial_errors:
            raise SystemExit(f"initial serving verification failed: {initial_errors}")

        candidate_profile = build_profile(
            candidate_target,
            candidate_settings,
            source_report=profile_dir / "production-soak.json",
            source_payload={"protocol": "mortal-rogs-serving-soak-v1", "elapsed_s": 1800.0},
        )
        result = apply_profile_transaction(
            path=profile,
            candidate_profile=candidate_profile,
            previous_target=previous_target,
            candidate_target=candidate_target,
            ops=ops,
            verify_timeout_s=120.0,
        )
        if result.get("ok") is not True or result.get("rolled_back") is not False:
            raise SystemExit(f"production apply did not succeed: {result}")
        saved_after_apply = profile.read_bytes()
        applied = json.loads(saved_after_apply.decode("utf-8"))
        if applied.get("status") != "active" or applied.get("serving", {}).get("micro_batch_ms") != 1.0:
            raise SystemExit(f"active production profile mismatch: {applied}")

        bad_target = {
            **candidate_target,
            "device": "definitely-invalid-device",
            "serving": normalize_serving_settings({**candidate_settings, "micro_batch_ms": 2.0}),
        }
        bad_profile = build_profile(
            bad_target,
            bad_target["serving"],
            source_report=profile_dir / "bad-soak.json",
            source_payload={"protocol": "mortal-rogs-serving-soak-v1", "elapsed_s": 1800.0},
        )
        try:
            apply_profile_transaction(
                path=profile,
                candidate_profile=bad_profile,
                previous_target=candidate_target,
                candidate_target=bad_target,
                ops=ops,
                verify_timeout_s=30.0,
            )
            raise SystemExit("invalid candidate unexpectedly passed production apply")
        except ProductionApplyError as exc:
            if exc.rollback.get("ok") is not True:
                raise SystemExit(f"production rollback failed: {exc.rollback}") from exc

        if profile.read_bytes() != saved_after_apply:
            raise SystemExit("production profile bytes were not restored after rollback")
        rollback_health = wait_healthy(candidate_target, 120.0)
        errors = verify_health(rollback_health, candidate_settings)
        if errors:
            raise SystemExit(f"rollback serving verification failed: {errors}")

        print("MORTAL_INFERENCE_PRODUCTION_APPLY_E2E_OK")
        print("MORTAL_INFERENCE_PRODUCTION_ROLLBACK_E2E_OK")
        print(json.dumps({"profile": str(profile), "serving": candidate_settings}, ensure_ascii=False, indent=2))
        return 0
    finally:
        stop()


if __name__ == "__main__":
    raise SystemExit(main())
