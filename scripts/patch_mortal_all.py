from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run(script: Path, *args: str) -> None:
    subprocess.run([sys.executable, str(script), *args], check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()

    project = Path(__file__).resolve().parents[1]
    root = args.root.resolve()
    train_py = root / "Mortal" / "mortal" / "train.py"
    if not train_py.is_file():
        raise FileNotFoundError(train_py)

    run(project / "scripts" / "patch_mortal.py", "--root", str(root))
    run(
        project / "scripts" / "patch_mortal_rogs_trainer.py",
        "--train-py",
        str(train_py),
    )
    print("MORTAL_ALL_PATCHES_OK RTX5080 runtime + ROGS trainer hook")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
