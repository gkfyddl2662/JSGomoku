from __future__ import annotations

import argparse
from pathlib import Path

MARKER = "MORTAL_ROGS_UNIFIED_DATASET_STAGE8B"
REQUIRES = "MORTAL_ROGS_UNIFIED_ACTION_OBS_STAGE3E"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_gameplay(text: str) -> str:
    if MARKER in text:
        return text

    text = "// " + MARKER + "\n" + text
    text = replace_once(
        text,
        "        let mut kan_select = None;\n        let label_opt = match *next {\n",
        "        let mut kan_select = None;\n"
        "        let is_sanma = state.num_players() == 3;\n"
        "        let label_opt = match *next {\n",
        "dataset mode detection",
    )

    text = replace_once(
        text,
        "            Event::Reach { .. } => Some(37),\n"
        "            Event::Chi {\n",
        "            Event::Reach { .. } => Some(37),\n"
        "            Event::Nukidora { actor, .. } if is_sanma && actor == self.player_id => Some(38),\n"
        "            Event::Chi {\n",
        "dataset nukidora label",
    )

    text = replace_once(
        text,
        "            Event::Pon { actor, .. } if actor == self.player_id => Some(41),\n",
        "            Event::Pon { actor, .. } if actor == self.player_id => {\n"
        "                Some(if is_sanma { 39 } else { 41 })\n"
        "            }\n",
        "dataset pon label",
    )

    for event in ("Daiminkan", "Kakan", "Ankan"):
        if event == "Daiminkan":
            old = (
                "            Event::Daiminkan { actor, pai, .. } if actor == self.player_id => {\n"
                "                if config.always_include_kan_select {\n"
                "                    kan_select = Some(pai.deaka().as_usize());\n"
                "                }\n"
                "                Some(42)\n"
                "            }\n"
            )
            new = (
                "            Event::Daiminkan { actor, pai, .. } if actor == self.player_id => {\n"
                "                if config.always_include_kan_select {\n"
                "                    kan_select = Some(pai.deaka().as_usize());\n"
                "                }\n"
                "                Some(if is_sanma { 40 } else { 42 })\n"
                "            }\n"
            )
        elif event == "Kakan":
            old = (
                "            Event::Kakan { pai, .. } => {\n"
                "                if config.always_include_kan_select || state.kakan_candidates().len() > 1 {\n"
                "                    kan_select = Some(pai.deaka().as_usize());\n"
                "                }\n"
                "                Some(42)\n"
                "            }\n"
            )
            new = (
                "            Event::Kakan { pai, .. } => {\n"
                "                if config.always_include_kan_select || state.kakan_candidates().len() > 1 {\n"
                "                    kan_select = Some(pai.deaka().as_usize());\n"
                "                }\n"
                "                Some(if is_sanma { 40 } else { 42 })\n"
                "            }\n"
            )
        else:
            old = (
                "            Event::Ankan { consumed, .. } => {\n"
                "                if config.always_include_kan_select || state.ankan_candidates().len() > 1 {\n"
                "                    kan_select = Some(consumed[0].deaka().as_usize());\n"
                "                }\n"
                "                Some(42)\n"
                "            }\n"
            )
            new = (
                "            Event::Ankan { consumed, .. } => {\n"
                "                if config.always_include_kan_select || state.ankan_candidates().len() > 1 {\n"
                "                    kan_select = Some(consumed[0].deaka().as_usize());\n"
                "                }\n"
                "                Some(if is_sanma { 40 } else { 42 })\n"
                "            }\n"
            )
        text = replace_once(text, old, new, f"dataset {event} label")

    text = replace_once(
        text,
        "            Event::Ryukyoku { .. } if cans.can_ryukyoku => Some(44),\n",
        "            Event::Ryukyoku { .. } if cans.can_ryukyoku => {\n"
        "                Some(if is_sanma { 42 } else { 44 })\n"
        "            }\n",
        "dataset ryukyoku label",
    )

    text = replace_once(
        text,
        "                                ret = Some(43);\n",
        "                                ret = Some(if is_sanma { 41 } else { 43 });\n",
        "dataset agari label",
    )

    text = replace_once(
        text,
        "                        ret = Some(45);\n",
        "                        ret = Some(if is_sanma { 43 } else { 45 });\n",
        "dataset pass label",
    )

    return text


def apply(root: Path) -> None:
    root = root.expanduser().resolve()
    consts = root / "libriichi/src/consts.rs"
    gameplay = root / "libriichi/src/dataset/gameplay.rs"
    if not consts.is_file() or REQUIRES not in consts.read_text(encoding="utf-8"):
        raise RuntimeError("Stage 8B requires unified action/observation Stage 3E")
    if not gameplay.is_file():
        raise RuntimeError(f"missing gameplay dataset source: {gameplay}")

    original = gameplay.read_text(encoding="utf-8")
    updated = patch_gameplay(original)
    if updated != original:
        gameplay.write_text(updated, encoding="utf-8")
        print(f"patched: {gameplay}")
    else:
        print(f"unchanged: {gameplay}")

    post = gameplay.read_text(encoding="utf-8")
    required = (
        MARKER,
        "let is_sanma = state.num_players() == 3;",
        "Event::Nukidora",
        "if is_sanma { 39 } else { 41 }",
        "if is_sanma { 40 } else { 42 }",
        "if is_sanma { 41 } else { 43 }",
        "if is_sanma { 42 } else { 44 }",
        "if is_sanma { 43 } else { 45 }",
    )
    missing = [token for token in required if token not in post]
    if missing:
        raise RuntimeError(f"Stage 8B postconditions failed: {missing}")
    print("MORTAL_UNIFIED_DATASET_STAGE8B_OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    apply(args.root)


if __name__ == "__main__":
    main()
