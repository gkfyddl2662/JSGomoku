from __future__ import annotations

import argparse
import gzip
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


def request_json(url: str, *, api_key: str = "", payload: dict | None = None, gzip_body: bool = False) -> tuple[int, dict]:
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
        with urllib.request.urlopen(req, timeout=15) as resp:
            return int(resp.status), json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            decoded = json.loads(body)
        except json.JSONDecodeError:
            decoded = {"raw": body}
        return int(exc.code), decoded


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
    model_3p = (args.model_3p or root / "runtime" / "smoke-training" / "smoke-trained-3p.pth").resolve()
    model_4p = (args.model_4p or root / "runtime" / "smoke-training" / "smoke-trained-4p.pth").resolve()
    for path in (model_3p, model_4p):
        if not path.is_file():
            raise SystemExit(f"API smoke checkpoint missing: {path}")

    port = free_port()
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
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(project), str(root / "mortal"), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    proc = subprocess.Popen(
        cmd,
        cwd=project,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 60
        health = None
        while time.time() < deadline:
            if proc.poll() is not None:
                output = proc.stdout.read() if proc.stdout else ""
                raise SystemExit(f"Inference API exited before readiness ({proc.returncode}):\n{output}")
            try:
                status, health = request_json(f"{base}/health")
                if status == 200:
                    break
            except OSError:
                pass
            time.sleep(0.25)
        else:
            raise SystemExit("Inference API did not become ready")

        bad_status, _ = request_json(
            f"{base}/react_batch_3p",
            api_key="wrong-key",
            payload={"obs": [[[0.0] * 34] * 1010], "masks": [[True] * 44]},
            gzip_body=True,
        )
        if bad_status != 401:
            raise SystemExit(f"Bad API key should return 401, got {bad_status}")

        results: dict[str, object] = {"health": health, "modes": {}}
        for mode, endpoint, obs_channels, actions in (
            ("3p", "/react_batch_3p", 1010, 44),
            ("4p", "/react_batch", 1012, 46),
        ):
            payload = {
                "obs": [[[0.0] * 34 for _ in range(obs_channels)] for _ in range(2)],
                "masks": [[True] * actions for _ in range(2)],
            }
            status, body = request_json(
                f"{base}{endpoint}", api_key=args.api_key, payload=payload, gzip_body=True
            )
            if status != 200:
                raise SystemExit(f"{mode} API returned HTTP {status}: {body}")
            if len(body.get("actions", [])) != 2:
                raise SystemExit(f"{mode} API action batch mismatch: {body}")
            if len(body.get("q_out", [])) != 2 or any(len(row) != actions for row in body["q_out"]):
                raise SystemExit(f"{mode} API q_out shape mismatch")
            if len(body.get("masks", [])) != 2 or any(len(row) != actions for row in body["masks"]):
                raise SystemExit(f"{mode} API mask shape mismatch")
            if body.get("is_greedy") != [True, True]:
                raise SystemExit(f"{mode} API greedy flags mismatch: {body.get('is_greedy')}")
            results["modes"][mode] = {
                "endpoint": endpoint,
                "batch": 2,
                "obs": [obs_channels, 34],
                "action_space": actions,
                "actions": body["actions"],
            }

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
                print(tail[-4000:])


if __name__ == "__main__":
    raise SystemExit(main())
