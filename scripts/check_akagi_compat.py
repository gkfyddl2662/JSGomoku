from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Strict Akagi-NG Mortal checkpoint compatibility probe")
    p.add_argument("--akagi-root", type=Path, required=True)
    p.add_argument("--model", type=Path, required=True)
    p.add_argument("--require-v4", action="store_true", default=False)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    root = args.akagi_root.resolve()
    model_path = args.model.resolve()
    backend = root / "akagi_backend"
    lib_dir = root / "lib"

    for path in (backend, lib_dir):
        if not path.exists():
            raise SystemExit(f"Missing Akagi-NG path: {path}")
        sys.path.insert(0, str(path))

    import torch

    try:
        import libriichi3p
    except ImportError as exc:
        raise SystemExit(
            "Could not import Akagi-NG libriichi3p. In source builds, copy/rename the platform-specific "
            "libriichi3p binary to the generic import name as described by Akagi-NG README."
        ) from exc

    from akagi_ng.mjai_bot.network import Brain, CategoricalPolicy, DQN

    state = torch.load(model_path, map_location="cpu", weights_only=False)
    required = {"config", "mortal"}
    missing = sorted(required - state.keys())
    if missing:
        raise SystemExit(f"Checkpoint missing required keys: {missing}")

    cfg = state["config"]
    version = int(cfg["control"]["version"])
    channels = int(cfg["resnet"]["conv_channels"])
    blocks = int(cfg["resnet"]["num_blocks"])
    if args.require_v4 and version != 4:
        raise SystemExit(f"ROGS deployment ABI requires Mortal v4, checkpoint is v{version}")
    if version not in (1, 2, 3, 4):
        raise SystemExit(f"Current Akagi-NG local loader supports Mortal versions 1-4, got v{version}")

    consts = libriichi3p.consts
    action_space = int(consts.ACTION_SPACE)
    if action_space != 44:
        raise SystemExit(f"Akagi-NG libriichi3p ACTION_SPACE must be 44, got {action_space}")

    obs_shape = tuple(int(x) for x in consts.obs_shape(version))
    is_policy = "policy_net" in state
    if not is_policy and "current_dqn" not in state:
        raise SystemExit("Checkpoint needs either current_dqn (standard Mortal) or policy_net (Akagi policy mode)")

    brain = Brain(
        obs_shape_func=consts.obs_shape,
        oracle_obs_shape_func=consts.oracle_obs_shape,
        version=version,
        conv_channels=channels,
        num_blocks=blocks,
        norm_type="GN" if is_policy else "BN",
    ).eval()
    head = CategoricalPolicy(action_space) if is_policy else DQN(action_space, version=version)
    head = head.eval()

    brain.load_state_dict(state["mortal"], strict=True)
    head.load_state_dict(state["policy_net" if is_policy else "current_dqn"], strict=True)

    with torch.inference_mode():
        obs = torch.zeros((2, *obs_shape), dtype=torch.float32)
        mask = torch.ones((2, action_space), dtype=torch.bool)
        phi = brain(obs)
        out = head(phi, mask)

    if tuple(out.shape) != (2, 44):
        raise SystemExit(f"Inference output must be [batch, 44], got {tuple(out.shape)}")
    if not torch.isfinite(out).all():
        raise SystemExit("Inference produced non-finite values")

    result = {
        "compatible": True,
        "akagi_root": str(root),
        "model": str(model_path),
        "model_version": version,
        "mode": "policy_net" if is_policy else "current_dqn",
        "obs_shape": obs_shape,
        "action_space": action_space,
        "conv_channels": channels,
        "num_blocks": blocks,
        "output_shape": tuple(out.shape),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
