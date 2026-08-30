from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Check Mortal v4 checkpoint against Akagi-NG 3P or 4P runtime ABI")
    p.add_argument("--akagi-root", type=Path, required=True)
    p.add_argument("--model", type=Path, required=True)
    p.add_argument("--mode", choices=("3p", "4p"), required=True)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    root = args.akagi_root.resolve()
    backend = root / "akagi_backend"
    lib_dir = root / "lib"
    for path in (backend, lib_dir):
        if not path.exists():
            raise SystemExit(f"Missing Akagi-NG path: {path}")
        sys.path.insert(0, str(path))

    import torch
    if args.mode == "3p":
        import libriichi3p as libs
        expected_actions = 44
    else:
        import libriichi as libs
        expected_actions = 46

    from akagi_ng.mjai_bot.network import Brain, DQN

    state = torch.load(args.model.resolve(), map_location="cpu", weights_only=False)
    for key in ("config", "mortal", "current_dqn"):
        if key not in state:
            raise SystemExit(f"Missing standard Mortal deployment key: {key}")

    cfg = state["config"]
    version = int(cfg["control"]["version"])
    if version != 4:
        raise SystemExit(f"ROGS deployment ABI is Mortal v4; got v{version}")

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
        norm_type="BN",
    ).eval()
    dqn = DQN(action_space, version=version).eval()
    brain.load_state_dict(state["mortal"], strict=True)
    dqn.load_state_dict(state["current_dqn"], strict=True)

    with torch.inference_mode():
        obs = torch.zeros((2, *obs_shape), dtype=torch.float32)
        mask = torch.ones((2, action_space), dtype=torch.bool)
        out = dqn(brain(obs), mask)

    if tuple(out.shape) != (2, expected_actions) or not torch.isfinite(out).all():
        raise SystemExit(f"Invalid inference output: shape={tuple(out.shape)} finite={bool(torch.isfinite(out).all())}")

    print(json.dumps({
        "compatible": True,
        "mode": args.mode,
        "version": version,
        "obs_shape": obs_shape,
        "action_space": action_space,
        "model": str(args.model.resolve()),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
