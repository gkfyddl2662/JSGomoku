from __future__ import annotations

import argparse
from pathlib import Path


MARKER = "MORTAL_ROGS_UNIFIED_GAME_STAGE5A_FIX"
REQUIRES = "MORTAL_ROGS_UNIFIED_GAME_STAGE5A"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def apply(root: Path) -> None:
    game = root / "libriichi/src/arena/game.rs"
    board = root / "libriichi/src/arena/board.rs"
    obs = root / "libriichi/src/state/obs_repr.rs"
    if not game.is_file() or REQUIRES not in game.read_text(encoding="utf-8"):
        raise RuntimeError("Stage 5A fix requires Stage 5A")

    game_text = game.read_text(encoding="utf-8")
    if MARKER not in game_text:
        game_text = replace_once(
            game_text,
            "            if self.kyotaku > 0 {\n"
            "                *self.scores[..self.active_players()]\n"
            "                    .iter_mut()\n"
            "                    .min_by_key(|s| -**s)\n"
            "                    .unwrap() += self.kyotaku as i32 * 1000;\n"
            "            }\n",
            "            if self.kyotaku > 0 {\n"
            "                let active = self.active_players();\n"
            "                *self.scores[..active]\n"
            "                    .iter_mut()\n"
            "                    .min_by_key(|s| -**s)\n"
            "                    .unwrap() += self.kyotaku as i32 * 1000;\n"
            "            }\n",
            "kyotaku active-score mutable borrow",
        )
        game_text = "// " + MARKER + "\n" + game_text
        game.write_text(game_text, encoding="utf-8")
        print(f"patched: {game}")
    else:
        print(f"unchanged: {game}")

    board_text = board.read_text(encoding="utf-8")
    if "use std::convert::TryInto;\n" in board_text:
        board.write_text(board_text.replace("use std::convert::TryInto;\n", "", 1), encoding="utf-8")
        print(f"cleaned: {board}")

    obs_text = obs.read_text(encoding="utf-8")
    if "self.mask[37] = true;" in obs_text:
        obs.write_text(
            obs_text.replace("self.mask[37] = true;", "self.mask[ACTION_RIICHI_3P] = true;", 1),
            encoding="utf-8",
        )
        print(f"cleaned: {obs}")

    post = game.read_text(encoding="utf-8")
    if MARKER not in post or "let active = self.active_players();" not in post:
        raise RuntimeError("Stage 5A borrow fix postcondition failed")
    print("MORTAL_UNIFIED_GAME_STAGE5A_FIX_OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, type=Path)
    args = ap.parse_args()
    apply(args.root.expanduser().resolve())


if __name__ == "__main__":
    main()
