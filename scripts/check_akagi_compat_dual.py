from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from pathlib import Path


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[1]
    p = argparse.ArgumentParser(description="Check Mortal v4 checkpoint against the pinned Akagi-NG 3P/4P runtime ABI")
    p.add_argument("--akagi-root", type=Path, required=True)
    p.add_argument("--model", type=Path, required=True)
    p.add_argument("--mode", choices=("3p", "4p"), required=True)
    p.add_argument("--abi", type=Path, default=project / "config" / "akagi_abi.toml")
    p.add_argument("--allow-akagi-drift", action="store_true")
    return p.parse_args()


def git_blob_sha(path: Path) -> str:
    return subprocess.run(
        ["git", "hash-object", str(path)], check=True, capture_output=True, text=True
    ).stdout.strip()


def verify_akagi_sources(root: Path, abi: dict, allow_drift: bool) -> dict[str, dict[str, str | bool]]:
    upstream = abi["upstream"]
    specs = {
        "mortal_loader": (upstream["mortal_loader_path"], upstream["mortal_loader_sha"]),
        "network": (upstream["network_path"], upstream["network_sha"]),
        "constants": (upstream["constants_path"], upstream["constants_sha"]),
    }
    report: dict[str, dict[str, str | bool]] = {}
    drift = []
    for name, (relative, expected) in specs.items():
        path = root / relative
        if not path.is_file():
            raise SystemExit(f"Missing pinned Akagi-NG source: {path}")
        actual = git_blob_sha(path)
        matches = actual == expected
        report[name] = {
            "path": str(path),
            "expected_sha": str(expected),
            "actual_sha": actual,
            "matches": matches,
        }
        if not matches:
            drift.append(name)
    if drift and not allow_drift:
        raise SystemExit(
            "Akagi-NG ABI source drift detected in " + ", ".join(drift) +
            ". Review upstream changes and update config/akagi_abi.toml before promotion."
        )
    return report


def main() -> int:
    args = parse_args()
    root = args.akagi_root.resolve()
    with args.abi.resolve().open("rb") as f:
        abi = tomllib.load(f)

    source_report = verify_akagi_sources(root, abi, args.allow_akagi_drift)
    backend = root / "akagi_backend"
    lib_dir = root / "lib"
    for path in (backend, lib_dir):
        if not path.exists():
            raise SystemExit(f"Missing Akagi-NG path: {path}")
        sys.path.insert(0, str(path))

    mode_cfg = abi["mode"][args.mode]
    expected_actions = int(mode_cfg["action_space"])
    expected_version = int(abi["checkpoint"]["model_version"])
    expected_keys = tuple(str(x) for x in abi["checkpoint"]["required_keys"])
    norm_type = str(abi["checkpoint"].get("norm_type", "BN"))

    import torch
    if args.mode == "3p":
        import libriichi3p as libs
    else:
        import libriichi as libs

    from akagi_ng.mjai_bot.network import Brain, DQN

    state = torch.load(args.model.resolve(), map_location="cpu", weights_only=False)
    for key in expected_keys:
        if key not in state:
            raise SystemExit(f"Missing standard Mortal deployment key: {key}")

    cfg = state["config"]
    version = int(cfg["control"]["version"])
    if version != expected_version:
        raise SystemExit(f"ROGS deployment ABI is Mortal v{expected_version}; got v{version}")

    action_space = int(libs.consts.ACTION_SPACE)
    if action_space != expected_actions:
        raise SystemExit(f"Akagi {args.mode} ACTION_SPACE mismatch: {action_space} != {expected_actions}")
    obs_shape = tuple(int(x) for x in libs.consts.obs_shape(version))

    brain = Brain(
        obs_shape_func=libs.consts.obs_shape,
        oracle_obs_shape_func=libs.consts.oracle_obs_shape,
        version=version,
        conv_channels=int(cfg["resnet"]["conv_channels"]),
        num_blocks=int(cfg["resnet"]["num_blocks"]),
        norm_type=norm_type,
    ).eval()
    dqn = DQN(action_space, version=version).eval()
    brain.load_state_dict(state["mortal"], strict=bool(abi["policy"].get("strict_state_dict", True)))
    dqn.load_state_dict(state["current_dqn"], strict=bool(abi["policy"].get("strict_state_dict", True)))

    with torch.inference_mode():
        obs = torch.zeros((2, *obs_shape), dtype=torch.float32)
        mask = torch.ones((2, action_space), dtype=torch.bool)
        out = dqn(brain(obs), mask)

    finite = bool(torch.isfinite(out).all())
    if tuple(out.shape) != (2, expected_actions) or not finite:
        raise SystemExit(f"Invalid inference output: shape={tuple(out.shape)} finite={finite}")

    print(json.dumps({
        "compatible": True,
        "mode": args.mode,
        "version": version,
        "obs_shape": obs_shape,
        "action_space": action_space,
        "model": str(args.model.resolve()),
        "akagi_source_match": all(bool(x["matches"]) for x in source_report.values()),
        "akagi_sources": source_report,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
