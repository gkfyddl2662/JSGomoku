from __future__ import annotations

import argparse
import py_compile
from pathlib import Path

MARKER = "# MORTAL_ROGS_UNIFIED_PYTHON_ABI_STAGE8A"


def replace(text: str, old: str, new: str) -> str:
    return text.replace(old, new) if old in text else text


def apply(root: Path) -> None:
    mortal = root.expanduser().resolve() / "mortal"
    if not mortal.is_dir():
        raise RuntimeError(f"missing mortal dir: {mortal}")

    replacements = {
        "train.py": [
            ("from libriichi.consts import obs_shape\n", "from libriichi import consts\nobs_shape = consts.obs_shape\n"),
        ],
        "dataloader.py": [
            ("from libriichi.dataset import GameplayLoader\n", "from libriichi import dataset as libriichi_dataset\nGameplayLoader = libriichi_dataset.GameplayLoader\n"),
        ],
        "train_grp.py": [
            ("from libriichi.dataset import Grp\n", "from libriichi import dataset as libriichi_dataset\nGrp = libriichi_dataset.Grp\n"),
        ],
        "player.py": [
            ("from libriichi.stat import Stat\n", "from libriichi import stat as libriichi_stat\nStat = libriichi_stat.Stat\n"),
            ("from libriichi.arena import OneVsThree, OneVsTwo\n", "from libriichi import arena as libriichi_arena\nOneVsThree = libriichi_arena.OneVsThree\nOneVsTwo = libriichi_arena.OneVsTwo\n"),
        ],
        "one_vs_two.py": [
            ("from libriichi.arena import OneVsTwo\n", "from libriichi import arena as libriichi_arena\nOneVsTwo = libriichi_arena.OneVsTwo\n"),
        ],
        "one_vs_three.py": [
            ("from libriichi.arena import OneVsThree\n", "from libriichi import arena as libriichi_arena\nOneVsThree = libriichi_arena.OneVsThree\n"),
        ],
    }

    for name, pairs in replacements.items():
        path = mortal / name
        if not path.is_file():
            if name == "one_vs_two.py":
                continue
            raise RuntimeError(f"missing Mortal Python file: {path}")
        text = path.read_text(encoding="utf-8")
        updated = text
        for old, new in pairs:
            updated = replace(updated, old, new)
        if MARKER not in updated:
            updated = MARKER + "\n" + updated
        if updated != text:
            path.write_text(updated, encoding="utf-8")
            print(f"patched: {path}")
        py_compile.compile(str(path), doraise=True)

    engine = mortal / "engine.py"
    text = engine.read_text(encoding="utf-8")
    if "game_mode = None," not in text:
        text = text.replace(
            "        top_p = 1,\n    ):\n",
            "        top_p = 1,\n        game_mode = None,\n        action_space = None,\n    ):\n",
            1,
        )
        text = text.replace(
            "        self.top_p = top_p\n",
            "        self.top_p = top_p\n        self.game_mode = game_mode\n        self.action_space = action_space\n",
            1,
        )
    if MARKER not in text:
        text = MARKER + "\n" + text
    engine.write_text(text, encoding="utf-8")
    py_compile.compile(str(engine), doraise=True)

    for path in mortal.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "from libriichi." in text:
            raise RuntimeError(f"legacy PyO3 submodule import remains: {path}")

    if "game_mode = None" not in engine.read_text(encoding="utf-8"):
        raise RuntimeError("MortalEngine unified metadata kwargs missing")
    print("MORTAL_UNIFIED_PYTHON_ABI_STAGE8A_OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    apply(args.root)


if __name__ == "__main__":
    main()
