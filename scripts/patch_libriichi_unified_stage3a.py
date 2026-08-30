from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


EVENT_SHA = "3b92f06ec354dc3204b647541f69c92a181ad9f4"
MARKER = "MORTAL_ROGS_UNIFIED_EVENT_STAGE3A"


def git_blob_sha(path: Path) -> str:
    return subprocess.run(
        ["git", "hash-object", str(path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_event(text: str) -> str:
    if MARKER in text:
        return text

    text = replace_once(
        text,
        "pub enum Event {\n",
        f"// {MARKER}\npub enum Event {{\n",
        "event marker",
    )
    text = replace_once(text, "        names: [String; 4],\n", "        names: Vec<String>,\n", "start_game names")
    text = replace_once(text, "        scores: [i32; 4],\n", "        scores: Vec<i32>,\n", "start_kyoku scores")
    text = replace_once(text, "        tehais: [[Tile; 13]; 4],\n", "        tehais: Vec<Vec<Tile>>,\n", "start_kyoku hands")
    text = replace_once(
        text,
        "    Ankan {\n        #[serde_as(deserialize_as = \"TryFromInto<Actor>\")]\n        actor: u8,\n        consumed: [Tile; 4],\n    },\n    Dora {\n",
        "    Ankan {\n"
        "        #[serde_as(deserialize_as = \"TryFromInto<Actor>\")]\n"
        "        actor: u8,\n"
        "        consumed: [Tile; 4],\n"
        "    },\n"
        "    Nukidora {\n"
        "        #[serde_as(deserialize_as = \"TryFromInto<Actor>\")]\n"
        "        actor: u8,\n"
        "        pai: Tile,\n"
        "    },\n"
        "    Dora {\n",
        "nukidora event",
    )
    text = text.replace("        deltas: Option<[i32; 4]>,\n", "        deltas: Option<Vec<i32>>,\n")
    text = replace_once(
        text,
        "            | Self::Ankan { actor, .. }\n            | Self::Reach { actor, .. } => Some(actor),\n",
        "            | Self::Ankan { actor, .. }\n"
        "            | Self::Nukidora { actor, .. }\n"
        "            | Self::Reach { actor, .. } => Some(actor),\n",
        "nukidora actor",
    )
    text = replace_once(
        text,
        "            Self::Tsumo { pai, .. } | Self::Dahai { pai, .. } => swap_tile(pai),\n",
        "            Self::Tsumo { pai, .. } | Self::Dahai { pai, .. } | Self::Nukidora { pai, .. } => swap_tile(pai),\n",
        "nukidora augment",
    )
    return text


def apply(root: Path) -> None:
    path = root / "libriichi" / "src" / "mjai" / "event.rs"
    if not path.is_file():
        raise RuntimeError(f"event.rs not found: {path}")
    original = path.read_text(encoding="utf-8")
    if MARKER not in original:
        actual = git_blob_sha(path)
        if actual != EVENT_SHA:
            raise RuntimeError(f"unexpected stock event.rs: expected {EVENT_SHA}, got {actual}")
    updated = patch_event(original)
    if updated != original:
        backup = path.with_suffix(".rs.unified-stage3a.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(updated, encoding="utf-8")
        print(f"patched: {path}")
    else:
        print(f"unchanged: {path}")

    post = path.read_text(encoding="utf-8")
    required = (
        MARKER,
        "names: Vec<String>",
        "scores: Vec<i32>",
        "tehais: Vec<Vec<Tile>>",
        "Nukidora {",
        "deltas: Option<Vec<i32>>",
        "Self::Nukidora { actor, .. }",
    )
    missing = [x for x in required if x not in post]
    if missing:
        raise RuntimeError(f"unified event Stage 3A postconditions failed: {missing}")
    print("MORTAL_UNIFIED_EVENT_STAGE3A_OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    apply(args.root.expanduser().resolve())


if __name__ == "__main__":
    main()
