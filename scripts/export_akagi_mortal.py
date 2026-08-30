from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import torch


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Export a training checkpoint as a strict Akagi-NG Mortal v4 checkpoint")
    p.add_argument("source", type=Path)
    p.add_argument("destination", type=Path)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    src = args.source.resolve()
    dst = args.destination.resolve()
    state = torch.load(src, map_location="cpu", weights_only=False)

    for key in ("config", "mortal", "current_dqn"):
        if key not in state:
            raise SystemExit(f"Training checkpoint missing required deployment key: {key}")

    cfg = state["config"]
    version = int(cfg["control"]["version"])
    if version != 4:
        raise SystemExit(f"Akagi-NG ROGS export is ABI-locked to Mortal v4; source is v{version}")

    export = {
        "config": cfg,
        "mortal": state["mortal"],
        "current_dqn": state["current_dqn"],
        "export_meta": {
            "format": "mortal-v4-akagi-ng",
            "source": src.name,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "training_only_keys_stripped": sorted(
                k for k in state.keys() if k not in {"config", "mortal", "current_dqn"}
            ),
        },
    }

    dst.parent.mkdir(parents=True, exist_ok=True)
    torch.save(export, dst)
    print(json.dumps(export["export_meta"], ensure_ascii=False, indent=2))
    print(f"saved: {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
