from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from serving.inference import LoadedModel, contract_for


def main() -> int:
    p = argparse.ArgumentParser(description="Validate a Mortal v4 checkpoint for the unified Akagi-facing inference API")
    p.add_argument("--runtime-root", type=Path, required=True)
    p.add_argument("--model", type=Path, required=True)
    p.add_argument("--mode", choices=("3p", "4p"), required=True)
    p.add_argument("--device", default="cpu")
    args = p.parse_args()

    root = args.runtime_root.expanduser().resolve()
    model_path = args.model.expanduser().resolve()
    contract = contract_for(args.mode)
    loaded = LoadedModel(args.mode, model_path, root / "mortal", args.device)

    obs = np.zeros((2, contract.obs_channels, 34), dtype=np.float32)
    masks = np.ones((2, contract.action_space), dtype=np.bool_)
    result = loaded.infer(obs, masks)
    if len(result["actions"]) != 2:
        raise SystemExit("Unexpected action batch size")
    if any(len(row) != contract.action_space for row in result["q_out"]):
        raise SystemExit("Unexpected q_out width")

    print("MORTAL_API_CHECKPOINT_OK")
    print(json.dumps({
        "mode": contract.mode,
        "model": str(model_path),
        "version": 4,
        "obs_shape": [contract.obs_channels, 34],
        "action_space": contract.action_space,
        "device": str(loaded.device),
        "output_shape": [2, contract.action_space],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
