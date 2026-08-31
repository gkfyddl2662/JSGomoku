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


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def request_json(url: str, *, api_key: str = "", timeout: float = 5.0) -> tuple[int, dict]:
    headers = {"Authorization": api_key} if api_key else {}
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status), json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"raw": raw}
        return int(exc.code), body


def wait_ready(proc: subprocess.Popen[str], base: str, api_key: str) -> None:
    deadline = time.time() + 180.0
    while time.time() < deadline:
        if proc.poll() is not None:
            output = proc.stdout.read() if proc.stdout else ""
            raise SystemExit(f"soak smoke server exited before readiness ({proc.returncode}):\n{output}")
        try:
            status, body = request_json(f"{base}/health", api_key=api_key, timeout=2.0)
            if status == 200 and body.get("protocol") == "akagiot-v1":
                return
        except OSError:
            pass
        time.sleep(0.25)
    raise SystemExit("soak smoke server did not become ready")


def main() -> int:
    parser = argparse.ArgumentParser(description="Real-checkpoint short smoke for the long-running inference soak runner")
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--api-key", default="mortal-rogs-soak-smoke")
    args = parser.parse_args()

    project = Path(__file__).resolve().parents[1]
    root = args.runtime_root.expanduser().resolve()
    model_3p = root / "runtime" / "smoke-training" / "smoke-trained-3p.pth"
    model_4p = root / "runtime" / "smoke-training" / "smoke-trained-4p.pth"
    for model in (model_3p, model_4p):
        if not model.is_file():
            raise SystemExit(f"soak smoke checkpoint missing: {model}")

    report_dir = root / "runtime" / "smoke-soak"
    report_dir.mkdir(parents=True, exist_ok=True)
    report = report_dir / "soak-smoke.json"
    if report.exists():
        report.unlink()

    port = free_port()
    base = f"http://127.0.0.1:{port}"
    server_cmd = [
        sys.executable,
        str(project / "scripts" / "serve_akagi_api.py"),
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
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(project), str(root / "mortal"), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    proc = subprocess.Popen(
        server_cmd,
        cwd=project,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        wait_ready(proc, base, args.api_key)
        soak_env = env.copy()
        soak_env["MORTAL_INFERENCE_API_KEY"] = args.api_key
        soak_cmd = [
            sys.executable,
            str(project / "scripts" / "soak_inference_api.py"),
            "--server",
            base,
            "--modes",
            "both",
            "--duration-s",
            "2",
            "--min-production-duration-s",
            "1",
            "--concurrency",
            "2",
            "--batch-rows",
            "1",
            "--sample-interval-s",
            "0.25",
            "--latency-budget-ms",
            "3000",
            "--p99-budget-ms",
            "3500",
            "--vram-ceiling-pct",
            "100",
            "--temperature-ceiling-c",
            "120",
            "--output",
            str(report),
            "--fail-on-gate",
        ]
        completed = subprocess.run(
            soak_cmd,
            cwd=project,
            env=soak_env,
            text=True,
            capture_output=True,
            timeout=90.0,
            check=False,
        )
        if completed.returncode != 0:
            raise SystemExit(f"soak smoke failed ({completed.returncode}):\n{completed.stdout}\n{completed.stderr}")
        if "MORTAL_INFERENCE_SOAK_OK" not in completed.stdout:
            raise SystemExit(f"soak marker missing:\n{completed.stdout}")
        if "MORTAL_INFERENCE_PRODUCTION_PRESET_OK" not in completed.stdout:
            raise SystemExit(f"production preset marker missing:\n{completed.stdout}")
        if not report.is_file():
            raise SystemExit("soak smoke report was not created")

        payload = json.loads(report.read_text(encoding="utf-8"))
        if payload.get("protocol") != "mortal-rogs-serving-soak-v1":
            raise SystemExit(f"soak report protocol mismatch: {payload.get('protocol')}")
        if payload.get("production_gate", {}).get("passed") is not True:
            raise SystemExit(f"short soak production gate failed: {payload.get('production_gate')}")
        preset = payload.get("production_preset", {})
        if preset.get("eligible") is not True or preset.get("settings", {}).get("max_device_executions") != 1:
            raise SystemExit(f"soak preset mismatch: {preset}")
        for mode in ("3p", "4p"):
            result = payload.get("modes", {}).get(mode, {})
            if result.get("successful_requests", 0) < 1 or result.get("failed_requests") != 0:
                raise SystemExit(f"soak did not exercise {mode}: {result}")
        device = payload.get("device_scheduler", {})
        if device.get("peak_active_executions") != 1:
            raise SystemExit(f"soak did not preserve shared-device serialization: {device}")

        print("MORTAL_INFERENCE_SOAK_E2E_OK")
        print("MORTAL_INFERENCE_PRODUCTION_PRESET_E2E_OK")
        print(json.dumps({"gate": payload["production_gate"], "preset": preset}, ensure_ascii=False, indent=2))
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
                print("--- soak inference-api output ---")
                print(output[-5000:])


if __name__ == "__main__":
    raise SystemExit(main())
