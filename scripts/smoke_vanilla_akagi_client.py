from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import json
import os
import platform
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


def akagi_binary_path(akagi_root: Path, module_name: str) -> Path:
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    machine = platform.machine().lower()
    if machine in {"amd64", "x86_64"}:
        arch = "x86_64"
    elif machine in {"arm64", "aarch64"}:
        arch = "aarch64"
    else:
        raise RuntimeError(f"Unsupported architecture for pinned Akagi native smoke: {machine}")

    if sys.platform == "win32":
        platform_tag = f"{arch}-pc-windows-msvc"
        suffix = ".pyd"
    elif sys.platform == "darwin":
        platform_tag = f"{arch}-apple-darwin"
        suffix = ".so"
    elif sys.platform.startswith("linux"):
        platform_tag = f"{arch}-unknown-linux-gnu"
        suffix = ".so"
    else:
        raise RuntimeError(f"Unsupported platform for pinned Akagi native smoke: {sys.platform}")

    path = akagi_root / "lib" / f"{module_name}-{py_version}-{platform_tag}{suffix}"
    if not path.is_file():
        raise RuntimeError(f"Pinned Akagi bundled native module is missing: {path}")
    return path


def load_akagi_native_module(akagi_root: Path, module_name: str):
    """Load Akagi's own bundled extension without copying or renaming its files."""
    path = akagi_binary_path(akagi_root, module_name)
    existing = sys.modules.pop(module_name, None)
    try:
        loader = importlib.machinery.ExtensionFileLoader(module_name, str(path))
        spec = importlib.util.spec_from_file_location(module_name, str(path), loader=loader)
        if spec is None:
            raise RuntimeError(f"Could not create import spec for {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        loader.exec_module(module)
        return module, path
    except Exception:
        sys.modules.pop(module_name, None)
        if existing is not None:
            sys.modules[module_name] = existing
        raise


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

        # A source checkout contains the same native modules as an Akagi release,
        # but with Python/platform-qualified filenames. Load those untouched files
        # directly into memory so Akagi's own core.lib_loader sees the exact module
        # names it expects. No Akagi file is copied, renamed, patched or written.
        akagi_riichi, riichi_path = load_akagi_native_module(akagi_root, "libriichi")
        akagi_riichi3p, riichi3p_path = load_akagi_native_module(akagi_root, "libriichi3p")
        if not hasattr(akagi_riichi, "consts") or not hasattr(akagi_riichi3p, "consts"):
            raise SystemExit("Pinned Akagi native modules did not expose consts")

        sys.path.insert(0, str(backend))

        # These classes come directly from the untouched Akagi-NG checkout.
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
            "akagi_native": {
                "4p": str(riichi_path),
                "3p": str(riichi3p_path),
            },
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

        print("MORTAL_VANILLA_AKAGI_NATIVE_READONLY_OK")
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
