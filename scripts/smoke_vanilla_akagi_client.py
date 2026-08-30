from __future__ import annotations

import argparse
import importlib
import importlib.machinery
import json
import logging
import os
import subprocess
import sys
import time
import types
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


def install_package_shell(name: str, path: Path) -> types.ModuleType:
    """Expose a package path without executing that package's __init__.py.

    Akagi-NG's source-tree package initializers eagerly import its local Mortal and
    state-tracker stack. The AkagiOT HTTP engine itself does not depend on those
    components, and a packaged Akagi installation already provides its own native
    libraries. For this read-only source integration smoke we therefore expose only
    the package paths needed to import AkagiOT's untouched source modules.
    """
    module = types.ModuleType(name)
    module.__package__ = name
    module.__path__ = [str(path)]
    module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, is_package=True)
    module.__spec__.submodule_search_locations = module.__path__
    sys.modules[name] = module
    return module


def load_vanilla_akagi_ot(backend: Path):
    """Import AkagiOTClient/AkagiOTEngine without activating Akagi local models.

    The imported class definitions still come from the untouched pinned Akagi-NG
    checkout. Only eager package initializers and their unrelated local-engine/native
    side effects are bypassed. This mirrors Mortal-ROGS's production boundary: Akagi
    owns state/UI/networking, while Mortal-ROGS owns every Mortal checkpoint.
    """
    akagi_pkg = backend / "akagi_ng"
    mjai_pkg = akagi_pkg / "mjai_bot"
    engine_pkg = mjai_pkg / "engine"
    target = engine_pkg / "akagi_ot.py"
    for path in (akagi_pkg, mjai_pkg, engine_pkg, target):
        if not path.exists():
            raise RuntimeError(f"Pinned Akagi API-only import path is missing: {path}")

    sys.path.insert(0, str(backend))
    try:
        # The root initializer is harmless and gives us Akagi's own version metadata.
        importlib.import_module("akagi_ng")

        # Avoid mjai_bot/__init__.py -> StateTracker -> core.lib_loader and
        # engine/__init__.py -> factory/provider -> local Mortal engine. Those are
        # intentionally outside this API-only integration contract.
        install_package_shell("akagi_ng.mjai_bot", mjai_pkg)
        install_package_shell("akagi_ng.mjai_bot.engine", engine_pkg)

        # Akagi's logger initializes files under the source checkout on import.
        # Supply a process-local logger for the read-only integration smoke only;
        # AkagiOT uses it solely for circuit-breaker status messages.
        logger_module = types.ModuleType("akagi_ng.mjai_bot.logger")
        logger_module.logger = logging.getLogger("akagi-ng-api-only-smoke")
        sys.modules[logger_module.__name__] = logger_module

        module = importlib.import_module("akagi_ng.mjai_bot.engine.akagi_ot")
        status_module = importlib.import_module("akagi_ng.mjai_bot.status")

        source = Path(module.__file__).resolve()
        if source != target.resolve():
            raise RuntimeError(f"AkagiOT source mismatch: expected {target}, got {source}")
        if "libriichi" in sys.modules or "libriichi3p" in sys.modules:
            raise RuntimeError("API-only AkagiOT import unexpectedly activated a native libriichi module")

        return module.AkagiOTClient, module.AkagiOTEngine, status_module.BotStatusContext, source
    finally:
        try:
            sys.path.remove(str(backend))
        except ValueError:
            pass


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

        AkagiOTClient, AkagiOTEngine, BotStatusContext, source = load_vanilla_akagi_ot(backend)

        client = AkagiOTClient(base, args.api_key)
        if client.session.headers.get("Authorization") != args.api_key:
            raise SystemExit("Vanilla AkagiOTClient Authorization header contract changed")
        if client.session.headers.get("Content-Encoding") != "gzip":
            raise SystemExit("Vanilla AkagiOTClient gzip request contract changed")

        results: dict[str, object] = {
            "akagi_sha": actual_sha,
            "server": base,
            "akagi_modified": False,
            "akagi_ot_source": str(source),
            "native_modules_loaded": False,
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

        print("MORTAL_VANILLA_AKAGI_API_ONLY_IMPORT_OK")
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
