from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from smoke_akagi_api import assert_mode_response, build_payload, free_port, request_json


PINNED_AKAGI_SHA = "11c0ffc0d70bf8142585b92405b4412976c9e205"


def git_text(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def wait_ready(proc: subprocess.Popen[str], base: str, api_key: str) -> dict:
    deadline = time.time() + 180
    while time.time() < deadline:
        if proc.poll() is not None:
            output = proc.stdout.read() if proc.stdout else ""
            raise RuntimeError(f"Mortal inference API exited before readiness ({proc.returncode}):\n{output}")
        try:
            status, health = request_json(f"{base}/health", api_key=api_key)
            if status == 200:
                return health
        except OSError:
            pass
        time.sleep(0.25)
    raise RuntimeError("Mortal inference API did not become ready")


def main() -> int:
    p = argparse.ArgumentParser(
        description="Run unmodified pinned Akagi-NG AkagiOTClient/AkagiOTEngine against Mortal-ROGS inference API."
    )
    p.add_argument("--runtime-root", type=Path, required=True)
    p.add_argument("--akagi-root", type=Path, required=True)
    p.add_argument("--device", default="cpu")
    p.add_argument("--model-3p", type=Path)
    p.add_argument("--model-4p", type=Path)
    p.add_argument("--api-key", default="mortal-rogs-vanilla-akagi-smoke")
    args = p.parse_args()

    project = Path(__file__).resolve().parents[1]
    runtime_root = args.runtime_root.expanduser().resolve()
    akagi_root = args.akagi_root.expanduser().resolve()
    if not (akagi_root / ".git").is_dir():
        raise SystemExit(f"Akagi-NG checkout is not a git repository: {akagi_root}")

    actual_sha = git_text(akagi_root, "rev-parse", "HEAD")
    if actual_sha != PINNED_AKAGI_SHA:
        raise SystemExit(f"Akagi-NG checkout must be pinned to {PINNED_AKAGI_SHA}, got {actual_sha}")
    before_status = git_text(akagi_root, "status", "--porcelain")
    if before_status:
        raise SystemExit(f"Akagi-NG checkout must be clean/read-only for this smoke:\n{before_status}")

    default_3p = runtime_root / "runtime" / "smoke-training" / "smoke-trained-3p.pth"
    default_4p = runtime_root / "runtime" / "smoke-training" / "smoke-trained-4p.pth"
    model_3p = args.model_3p.expanduser().resolve() if args.model_3p else default_3p.resolve()
    model_4p = args.model_4p.expanduser().resolve() if args.model_4p else default_4p.resolve()
    for mode, path in (("3p", model_3p), ("4p", model_4p)):
        if not path.is_file():
            raise SystemExit(f"{mode} API smoke checkpoint missing: {path}")

    port = free_port()
    base = f"http://127.0.0.1:{port}"
    server = project / "scripts" / "serve_akagi_api.py"
    cmd = [
        sys.executable,
        str(server),
        "--runtime-root",
        str(runtime_root),
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
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(project), str(runtime_root / "mortal"), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
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
            raise SystemExit(f"Mortal API did not become healthy for vanilla Akagi smoke: {health}")

        backend = akagi_root / "akagi_backend"
        if not (backend / "akagi_ng" / "mjai_bot" / "engine" / "akagi_ot.py").is_file():
            raise SystemExit(f"Pinned Akagi-NG backend is incomplete: {backend}")
        sys.path.insert(0, str(backend))

        # These imports come directly from the untouched Akagi-NG checkout.
        from akagi_ng.mjai_bot.engine.akagi_ot import AkagiOTClient, AkagiOTEngine
        from akagi_ng.mjai_bot.status import BotStatusContext

        client = AkagiOTClient(base, args.api_key)
        if client.session.headers.get("Authorization") != args.api_key:
            raise SystemExit("Vanilla AkagiOTClient Authorization header contract changed")
        if client.session.headers.get("Content-Encoding") != "gzip":
            raise SystemExit("Vanilla AkagiOTClient gzip request contract changed")

        results: dict[str, object] = {
            "akagi_sha": actual_sha,
            "server": base,
            "akagi_modified": False,
            "modes": {},
        }
        for mode, is_3p, obs_channels, action_space, endpoint in (
            ("3p", True, 1010, 44, "/react_batch_3p"),
            ("4p", False, 1012, 46, "/react_batch"),
        ):
            payload, expected_actions = build_payload(obs_channels, action_space)
            obs = np.asarray(payload["obs"], dtype=np.float32)
            masks = np.asarray(payload["masks"], dtype=np.bool_)
            engine = AkagiOTEngine(BotStatusContext(), is_3p=is_3p, client=client)
            actions, q_out, returned_masks, is_greedy = engine.react_batch(obs, masks)
            body = {
                "actions": actions,
                "q_out": q_out,
                "masks": returned_masks,
                "is_greedy": is_greedy,
            }
            assert_mode_response(mode, body, actions=action_space, expected_actions=expected_actions)
            results["modes"][mode] = {
                "endpoint": endpoint,
                "obs": [obs_channels, 34],
                "action_space": action_space,
                "actions": actions,
                "client": "AkagiOTClient",
                "engine": "AkagiOTEngine",
            }

        after_status = git_text(akagi_root, "status", "--porcelain")
        if after_status:
            raise SystemExit(f"Vanilla Akagi-NG checkout was modified by integration smoke:\n{after_status}")

        print("MORTAL_VANILLA_AKAGI_CLIENT_3P_OK")
        print("MORTAL_VANILLA_AKAGI_CLIENT_4P_OK")
        print("MORTAL_VANILLA_AKAGI_CLIENT_E2E_OK")
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
                print("--- Mortal inference API output ---")
                print(tail[-4000:])


if __name__ == "__main__":
    raise SystemExit(main())
