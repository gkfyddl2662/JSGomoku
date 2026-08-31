from __future__ import annotations

import argparse
import shutil
from pathlib import Path


MARKER = "MORTAL_ROGS_UNIFIED_ARENA_STAGE4C"
REQUIRES = "MORTAL_ROGS_UNIFIED_ARENA_STAGE4B"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        if new in text:
            return text
        raise RuntimeError(f"{label}: anchor not found")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_consts(text: str) -> str:
    if MARKER in text:
        return text
    text = "// " + MARKER + "\n" + text
    text = replace_once(
        text,
        "        \"3p\" => match version {\n"
        "            1 => Ok((211, 34)),\n"
        "            2..=4 => Ok((217, 34)),\n"
        "            _ => Err(PyValueError::new_err(format!(\n"
        "                \"unsupported 3P Mortal version: {version}\"\n"
        "            ))),\n"
        "        },\n",
        "        \"3p\" => match version {\n"
        "            1 => Ok((211, 34)),\n"
        "            2 | 3 => Ok((217, 34)),\n"
        "            4 => Ok((170, 34)),\n"
        "            _ => Err(PyValueError::new_err(format!(\n"
        "                \"unsupported 3P Mortal version: {version}\"\n"
        "            ))),\n"
        "        },\n",
        "3P v4 oracle shape",
    )
    return text


def patch_board(text: str) -> str:
    if MARKER in text:
        return text
    if REQUIRES not in text:
        raise RuntimeError("Stage 4C requires unified arena Stage 4B")
    text = "// " + MARKER + "\n" + text

    text = replace_once(
        text,
        "    pub fn encode_oracle_obs(&self, perspective: u8, version: u32) -> Array2<f32> {\n"
        "        assert!(\n"
        "            self.num_players == 4,\n"
        "            \"3P arena oracle encoding requires unified arena Stage 4C\"\n"
        "        );\n"
        "        let shape = oracle_obs_shape(version);\n",
        "    pub fn encode_oracle_obs(&self, perspective: u8, version: u32) -> Array2<f32> {\n"
        "        let active = self.active_players();\n"
        "        assert!((perspective as usize) < active);\n"
        "        let shape = if self.num_players == 3 {\n"
        "            assert_eq!(version, 4, \"unified sanma oracle currently targets Mortal v4\");\n"
        "            (170, 34)\n"
        "        } else {\n"
        "            oracle_obs_shape(version)\n"
        "        };\n",
        "mode-aware oracle shape",
    )

    text = replace_once(
        text,
        "        self.player_states\n"
        "            .iter()\n"
        "            .cycle()\n"
        "            .skip(perspective as usize + 1)\n"
        "            .take(3)\n",
        "        self.player_states[..active]\n"
        "            .iter()\n"
        "            .cycle()\n"
        "            .skip(perspective as usize + 1)\n"
        "            .take(active - 1)\n",
        "active oracle opponents",
    )

    text = replace_once(
        text,
        "        idx += (69 - self.tiles_left as usize) * 2;\n",
        "        let hidden_live_cap = if self.num_players == 3 { 54 } else { 69 };\n"
        "        idx += (hidden_live_cap - self.tiles_left as usize) * 2;\n",
        "mode-aware oracle live wall padding",
    )

    tests = r'''

#[cfg(test)]
mod unified_arena_stage4c_tests {
    use super::*;

    #[test]
    fn unified_arena_stage4c_sanma_oracle_is_170_channels() {
        let mut board = Board {
            num_players: 3,
            scores: [35_000, 35_000, 35_000, 0],
            ..Default::default()
        };
        board.init_from_seed((17, 23));
        let mut state = board.into_state();
        state.haipai().unwrap();
        assert_eq!(state.tiles_left, 54);
        for perspective in 0..3 {
            let obs = state.encode_oracle_obs(perspective, 4);
            assert_eq!(obs.dim(), (170, 34));
        }
    }

    #[test]
    fn unified_arena_stage4c_yonma_oracle_stays_217_channels() {
        let mut board = Board {
            scores: [25_000; 4],
            ..Default::default()
        };
        board.init_from_seed((17, 23));
        let mut state = board.into_state();
        state.haipai().unwrap();
        assert_eq!(state.tiles_left, 69);
        let obs = state.encode_oracle_obs(0, 4);
        assert_eq!(obs.dim(), (217, 34));
    }
}
'''
    text = text.rstrip() + tests.rstrip() + "\n"
    return text


def patch_file(path: Path, transform) -> None:
    original = path.read_text(encoding="utf-8")
    updated = transform(original)
    if updated != original:
        backup = path.with_suffix(path.suffix + ".unified-stage4c.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(updated, encoding="utf-8")
        print(f"patched: {path}")
    else:
        print(f"unchanged: {path}")


def apply(root: Path) -> None:
    board = root / "libriichi/src/arena/board.rs"
    consts = root / "libriichi/src/consts.rs"
    if not board.is_file() or not consts.is_file():
        raise RuntimeError("missing unified libriichi files")
    if REQUIRES not in board.read_text(encoding="utf-8"):
        raise RuntimeError("Stage 4C requires Stage 4B")

    patch_file(consts, patch_consts)
    patch_file(board, patch_board)

    board_text = board.read_text(encoding="utf-8")
    consts_text = consts.read_text(encoding="utf-8")
    required = (
        "(170, 34)",
        "self.player_states[..active]",
        "hidden_live_cap",
        "unified_arena_stage4c_sanma_oracle_is_170_channels",
    )
    missing = [x for x in required if x not in board_text]
    if '4 => Ok((170, 34))' not in consts_text:
        missing.append("3P v4 const oracle shape 170")
    if missing:
        raise RuntimeError(f"Stage 4C postconditions failed: {missing}")
    if "3P arena oracle encoding requires unified arena Stage 4C" in board_text:
        raise RuntimeError("old 3P oracle safety gate remains")
    print("MORTAL_UNIFIED_ARENA_STAGE4C_OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    apply(args.root.expanduser().resolve())


if __name__ == "__main__":
    main()
