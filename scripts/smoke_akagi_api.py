from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
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


def touch_new_signature(path: Path) -> None:
    now = time.time_ns()
    os.utime(path, ns=(now, now))


def build_payload(obs_channels: int, actions: int) -> tuple[dict, list[int]]:
    # Singleton legal masks make the expected action deterministic without knowing
    # anything about the random smoke checkpoint's Q values.
    expected = [0, actions - 1]
    masks: list[list[bool]] = []
    for action in expected:
        row = [False] * actions
        row[action] = True
        masks.append(row)
    return {
        "obs": [[[0.0] * 34 for _ in range(obs_channels)] for _ in range(2)],
        "masks": masks,
    }, expected


def assert_mode_response(mode: str, body: dict, *, actions: int, expected_actions: list[int]) -> None:
    if body.get("actions") != expected_actions:
        raise SystemExit(f"{mode} API selected illegal/unexpected actions: {body.get('actions')} vs {expected_actions}")
    if len(body.get("q_out", [])) != 2 or any(len(row) != actions for row in body["q_out"]):
        raise SystemExit(f"{mode} API q_out shape mismatch")
    if len(body.get("masks", [])) != 2 or any(len(row) != actions for row in body["masks"]):
        raise SystemExit(f"{mode} API mask shape mismatch")
    if body.get("is_greedy") != [True, True]:
        raise SystemExit(f"{mode} API greedy flags mismatch: {body.get('is_greedy')}")
    for row_index, legal_action in enumerate(expected_actions):
        for action_index, value in enumerate(body["q_out"][row_index]):
            if action_index != legal_action and value > -1.0e8:
                raise SystemExit(f"{mode} API did not sanitize illegal Q value at row={row_index} action={action_index}")


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

    # Work on copies so the hot-reload failure test cannot damage training output.
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

        if health.get("protocol") != "akagiot-v1":
            raise SystemExit(f"Unexpected API protocol health marker: {health}")

        bad_status, _ = request_json(
            f"{base}/react_batch_3p",
            api_key="wrong-key",
            payload=build_payload(1010, 44)[0],
            gzip_body=True,
        )
        if bad_status != 401:
            raise SystemExit(f"Bad API key should return 401, got {bad_status}")

        wrong_shape_status, _ = request_json(
            f"{base}/react_batch_3p",
            api_key=args.api_key,
            payload=build_payload(1012, 46)[0],
            gzip_body=True,
        )
        if wrong_shape_status != 400:
            raise SystemExit(f"4P-shaped payload on 3P endpoint should return 400, got {wrong_shape_status}")

        results: dict[str, object] = {"health": health, "modes": {}}
        mode_payloads: dict[str, tuple[str, dict, list[int], int]] = {}
        for mode, endpoint, obs_channels, actions in (
            ("3p", "/react_batch_3p", 1010, 44),
            ("4p", "/react_batch", 1012, 46),
        ):
            payload, expected_actions = build_payload(obs_channels, actions)
            mode_payloads[mode] = (endpoint, payload, expected_actions, actions)
            status, body = request_json(
                f"{base}{endpoint}", api_key=args.api_key, payload=payload, gzip_body=True
            )
            if status != 200:
                raise SystemExit(f"{mode} API returned HTTP {status}: {body}")
            assert_mode_response(mode, body, actions=actions, expected_actions=expected_actions)
            results["modes"][mode] = {
                "endpoint": endpoint,
                "batch": 2,
                "obs": [obs_channels, 34],
                "action_space": actions,
                "actions": body["actions"],
            }

        status, loaded_health = request_json(f"{base}/health")
        if status != 200:
            raise SystemExit("Health failed after initial model loads")
        cuda_expected = args.device.strip().casefold().startswith("cuda")
        for mode in ("3p", "4p"):
            info = loaded_health["models"][mode]
            if not info["loaded"] or not info["current"] or info["last_error"] is not None:
                raise SystemExit(f"{mode} model did not become current after load: {info}")
            if cuda_expected:
                if info.get("compiled") is not True:
                    raise SystemExit(f"{mode} CUDA API model did not enable torch.compile: {info}")
                if info.get("amp_dtype") != "bfloat16":
                    raise SystemExit(f"{mode} CUDA API model did not enable BF16 AMP: {info}")
        if loaded_health.get("degraded"):
            raise SystemExit(f"Healthy loaded API unexpectedly degraded: {loaded_health}")

        # Atomic hot-reload safety: replace the 3P file with a valid 4P checkpoint.
        # The next 3P request must continue on the previously loaded 3P model while
        # surfacing the rejected replacement in /health.
        shutil.copyfile(source_4p, model_3p)
        touch_new_signature(model_3p)
        endpoint, payload, expected_actions, actions = mode_payloads["3p"]
        status, body = request_json(f"{base}{endpoint}", api_key=args.api_key, payload=payload, gzip_body=True)
        if status != 200:
            raise SystemExit(f"3P hot-reload fallback should keep serving, got HTTP {status}: {body}")
        assert_mode_response("3p-hot-reload-fallback", body, actions=actions, expected_actions=expected_actions)

        _, degraded_health = request_json(f"{base}/health")
        info = degraded_health["models"]["3p"]
        if not degraded_health.get("degraded") or info["current"] or not info["last_error"]:
            raise SystemExit(f"Rejected 3P replacement was not reported as degraded: {degraded_health}")
        if "does not match endpoint 3p" not in info["last_error"]:
            raise SystemExit(f"Unexpected 3P hot-reload rejection reason: {info['last_error']}")

        # Restore the valid 3P checkpoint and verify automatic recovery/reload.
        shutil.copyfile(source_3p, model_3p)
        touch_new_signature(model_3p)
        status, body = request_json(f"{base}{endpoint}", api_key=args.api_key, payload=payload, gzip_body=True)
        if status != 200:
            raise SystemExit(f"3P hot-reload recovery failed HTTP {status}: {body}")
        assert_mode_response("3p-hot-reload-recovery", body, actions=actions, expected_actions=expected_actions)
        _, recovered_health = request_json(f"{base}/health")
        info = recovered_health["models"]["3p"]
        if recovered_health.get("degraded") or not info["current"] or info["last_error"] is not None:
            raise SystemExit(f"3P slot did not recover after restoring checkpoint: {recovered_health}")

        results["performance"] = {
            "device": args.device,
            "cuda_compile_required": cuda_expected,
            "compiled": {mode: loaded_health["models"][mode].get("compiled") for mode in ("3p", "4p")},
            "amp_dtype": {mode: loaded_health["models"][mode].get("amp_dtype") for mode in ("3p", "4p")},
        }
        results["hot_reload"] = {
            "wrong_mode_rejected": True,
            "old_model_kept_serving": True,
            "health_degraded_on_reject": True,
            "automatic_recovery": True,
        }
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
                print(tail[-4000:])


if __name__ == "__main__":
    raise SystemExit(main())
