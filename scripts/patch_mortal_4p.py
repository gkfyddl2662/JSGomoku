from __future__ import annotations

import argparse
from pathlib import Path

from patch_mortal import patch_file, patch_grp, patch_model, patch_train
from patch_mortal_rogs_trainer import apply as patch_rogs_trainer


def main() -> int:
    parser = argparse.ArgumentParser(description="Patch stock Equim-chan/Mortal for RTX 5080 + ROGS without changing the v4 deployment ABI.")
    parser.add_argument("--root", type=Path, required=True, help="Path to an Equim-chan/Mortal clone")
    args = parser.parse_args()

    root = args.root.expanduser().resolve()
    mortal = root / "mortal"
    required = (mortal / "train.py", mortal / "train_grp.py", mortal / "model.py")
    missing = [str(p) for p in required if not p.is_file()]
    if missing:
        raise SystemExit("Missing stock Mortal files: " + ", ".join(missing))

    patch_file(mortal / "train.py", patch_train)
    patch_file(mortal / "model.py", patch_model)
    patch_file(mortal / "train_grp.py", patch_grp)
    patch_rogs_trainer(mortal / "train.py")

    text = (mortal / "train.py").read_text(encoding="utf-8")
    required_tokens = (
        "from training.mortal_hook import compute_mortal_rogs_batch",
        "performance",
        "amp_dtype",
        "enable_behavior_cloning=not online",
    )
    for token in required_tokens:
        if token not in text:
            raise RuntimeError(f"4P Mortal patch postcondition missing: {token}")

    print(f"MORTAL_4P_PATCH_OK {mortal}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
