from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


MARKER = "MORTAL_ROGS_UNIFIED_EVENT_BOUNDARY_STAGE3B"
EXPECTED = {
    "libriichi/src/arena/board.rs": "5c52ab995ebb9584327a8b33cd1ecdbdf1050c6e",
    "libriichi/src/arena/result.rs": "452bb3ce9ed8815edc56d5c1ccd415257748cdf1",
    "libriichi/src/dataset/grp.rs": "f2c257a563f76e3cee32cf31816d48ac1abd682f",
    "libriichi/src/state/update.rs": "7b6eca21c8e5a1a83a3642192b8f8c96034cacb2",
}


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


def replace_count(text: str, old: str, new: str, count: int, label: str) -> str:
    if old not in text and text.count(new) >= count:
        return text
    actual = text.count(old)
    if actual != count:
        raise RuntimeError(f"{label}: expected {count} anchors, found {actual}")
    return text.replace(old, new)


def patch_board(text: str) -> str:
    if MARKER in text:
        return text
    text = "// " + MARKER + "\n" + text
    text = replace_once(
        text,
        "            scores: self.board.scores,\n",
        "            scores: self.board.scores.to_vec(),\n",
        "arena scores event",
    )
    text = replace_once(
        text,
        "            tehais: self.board.haipai,\n",
        "            tehais: self.board.haipai.iter().map(|hand| hand.to_vec()).collect(),\n",
        "arena hands event",
    )
    text = replace_count(
        text,
        "deltas: Some(deltas),",
        "deltas: Some(deltas.to_vec()),",
        3,
        "arena score deltas",
    )
    text = replace_once(
        text,
        "deltas: Some([0; 4]),",
        "deltas: Some(vec![0; 4]),",
        "arena zero deltas",
    )
    return text


def patch_result(text: str) -> str:
    if MARKER in text:
        return text
    text = "// " + MARKER + "\n" + text
    return replace_once(
        text,
        "            names: self.names.clone(),\n",
        "            names: self.names.to_vec(),\n",
        "arena result names",
    )


def patch_grp(text: str) -> str:
    if MARKER in text:
        return text
    text = "// " + MARKER + "\n" + text
    text = replace_once(
        text,
        "                Event::Hora { deltas, .. } | Event::Ryukyoku { deltas, .. } => {\n"
        "                    if rank_by_player_opt.is_none() {\n"
        "                        let ds = deltas.context(\n",
        "                Event::Hora { ref deltas, .. } | Event::Ryukyoku { ref deltas, .. } => {\n"
        "                    if rank_by_player_opt.is_none() {\n"
        "                        let ds = deltas.as_ref().context(\n",
        "GRP borrow deltas",
    )
    text = replace_once(
        text,
        "                    scores,\n                    ..\n                } => {\n"
        "                    if rank_by_player_opt.is_none() {\n"
        "                        final_scores = scores;\n",
        "                    ref scores,\n                    ..\n                } => {\n"
        "                    if rank_by_player_opt.is_none() {\n"
        "                        final_scores.fill(0);\n"
        "                        let active = scores.len().min(final_scores.len());\n"
        "                        final_scores[..active].copy_from_slice(&scores[..active]);\n",
        "GRP normalize scores",
    )
    return text


def patch_stat(text: str) -> str:
    if MARKER in text:
        return text
    text = "// " + MARKER + "\n" + text
    text = replace_once(
        text,
        "            Event::StartKyoku { oya, scores, .. } => {\n"
        "                stat.round += 1;\n"
        "                cur_scores = scores;\n",
        "            Event::StartKyoku { oya, ref scores, .. } => {\n"
        "                stat.round += 1;\n"
        "                cur_scores.fill(0);\n"
        "                let active = scores.len().min(cur_scores.len());\n"
        "                cur_scores[..active].copy_from_slice(&scores[..active]);\n",
        "stat normalize scores",
    )
    text = text.replace(
        "Event::Hora {\n                actor,\n                target,\n                deltas,",
        "Event::Hora {\n                actor,\n                target,\n                ref deltas,",
    )
    text = text.replace(
        "let deltas = deltas.expect(\"deltas is required for analyzing\");",
        "let deltas = deltas.as_ref().expect(\"deltas is required for analyzing\");",
    )
    text = replace_once(
        text,
        "            Event::Ryukyoku { deltas } => {\n"
        "                let deltas = deltas.as_ref().expect(\"deltas is required for analyzing\");\n",
        "            Event::Ryukyoku { ref deltas } => {\n"
        "                let deltas = deltas.as_ref().expect(\"deltas is required for analyzing\");\n",
        "stat borrow ryukyoku deltas",
    )
    return text


def patch_update(text: str) -> str:
    if MARKER in text:
        return text
    text = "// " + MARKER + "\n" + text
    text = replace_once(
        text,
        "                scores,\n                tehais,\n            } => self.start_kyoku(\n",
        "                ref scores,\n                ref tehais,\n            } => self.start_kyoku(\n",
        "state borrow start event",
    )
    text = replace_once(
        text,
        "        scores: [i32; 4],\n        tehais: [[Tile; 13]; 4],\n    ) -> Result<()> {\n",
        "        scores: &[i32],\n        tehais: &[Vec<Tile>],\n    ) -> Result<()> {\n"
        "        ensure!(matches!(scores.len(), 3 | 4), \"expected 3 or 4 scores, got {}\", scores.len());\n"
        "        ensure!(tehais.len() == scores.len(), \"hand count {} != score count {}\", tehais.len(), scores.len());\n"
        "        ensure!(self.player_id as usize < scores.len(), \"player {} is inactive for {}P\", self.player_id, scores.len());\n"
        "        ensure!(tehais.iter().all(|hand| hand.len() == 13), \"every initial hand must contain 13 tiles\");\n",
        "state start signature",
    )
    text = replace_once(
        text,
        "        self.scores = scores;\n        self.scores.rotate_left(self.player_id as usize);\n",
        "        self.scores.fill(0);\n"
        "        self.scores[..scores.len()].copy_from_slice(scores);\n"
        "        self.scores.rotate_left(self.player_id as usize);\n",
        "state score normalize",
    )
    return text


def patch_file(root: Path, rel: str, transform) -> None:
    path = root / rel
    if not path.is_file():
        raise RuntimeError(f"missing upstream file: {path}")
    original = path.read_text(encoding="utf-8")
    expected = EXPECTED.get(rel)
    if MARKER not in original and expected is not None:
        actual = git_blob_sha(path)
        if actual != expected:
            raise RuntimeError(f"unexpected upstream {rel}: expected {expected}, got {actual}")
    updated = transform(original)
    if updated != original:
        backup = path.with_suffix(path.suffix + ".unified-stage3b.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(updated, encoding="utf-8")
        print(f"patched: {path}")
    else:
        print(f"unchanged: {path}")


def apply(root: Path) -> None:
    patch_file(root, "libriichi/src/arena/board.rs", patch_board)
    patch_file(root, "libriichi/src/arena/result.rs", patch_result)
    patch_file(root, "libriichi/src/dataset/grp.rs", patch_grp)
    patch_file(root, "libriichi/src/stat.rs", patch_stat)
    patch_file(root, "libriichi/src/state/update.rs", patch_update)

    for rel in (
        "libriichi/src/arena/board.rs",
        "libriichi/src/arena/result.rs",
        "libriichi/src/dataset/grp.rs",
        "libriichi/src/stat.rs",
        "libriichi/src/state/update.rs",
    ):
        if MARKER not in (root / rel).read_text(encoding="utf-8"):
            raise RuntimeError(f"Stage 3B marker missing: {rel}")
    print("MORTAL_UNIFIED_EVENT_BOUNDARY_STAGE3B_OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    apply(args.root.expanduser().resolve())


if __name__ == "__main__":
    main()
