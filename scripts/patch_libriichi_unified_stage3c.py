from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


MARKER = "MORTAL_ROGS_UNIFIED_PLAYER_STATE_STAGE3C"
REQUIRES = "MORTAL_ROGS_UNIFIED_EVENT_BOUNDARY_STAGE3B"
EXPECTED = {
    "libriichi/src/state/player_state.rs": "269b2e74a8dac499de6498911b381aa5431ea352",
    "libriichi/src/state/action.rs": "64bbc9f1b4afd5ebbc93fdbf35e420761aa27d06",
    "libriichi/src/state/getter.rs": "fac587bc6bbae5bc66aa423fb1e016a6298042bb",
    "libriichi/src/rankings.rs": "4b72572d97f1c3f1bfcaa440a64b81d0662f4fb6",
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


def patch_player_state(text: str) -> str:
    if MARKER in text:
        return text
    text = "// " + MARKER + "\n" + text
    return replace_once(
        text,
        "    pub(super) player_id: u8,\n\n",
        "    pub(super) player_id: u8,\n"
        "    #[derivative(Default(value = \"4\"))]\n"
        "    pub(super) num_players: u8,\n\n",
        "player-state num_players",
    )


def patch_getter(text: str) -> str:
    if MARKER in text:
        return text
    text = "// " + MARKER + "\n" + text
    return replace_once(
        text,
        "    pub const fn player_id(&self) -> u8 {\n"
        "        self.player_id\n"
        "    }\n",
        "    pub const fn player_id(&self) -> u8 {\n"
        "        self.player_id\n"
        "    }\n"
        "    #[getter]\n"
        "    #[inline]\n"
        "    #[must_use]\n"
        "    pub const fn num_players(&self) -> u8 {\n"
        "        self.num_players\n"
        "    }\n",
        "num_players getter",
    )


def patch_action(text: str) -> str:
    if MARKER in text:
        return text
    text = "// " + MARKER + "\n" + text
    text = replace_once(text, "use crate::tuz;\n", "use crate::{t, tuz};\n", "action t macro")
    text = replace_once(
        text,
        "    #[pyo3(get)]\n    pub can_riichi: bool,\n",
        "    #[pyo3(get)]\n    pub can_riichi: bool,\n"
        "    #[pyo3(get)]\n    pub can_nukidora: bool,\n",
        "nukidora candidate",
    )
    text = replace_once(
        text,
        "            || self.can_riichi\n            || self.can_agari()\n",
        "            || self.can_riichi\n            || self.can_nukidora\n            || self.can_agari()\n",
        "nukidora can_act",
    )
    text = replace_once(
        text,
        "            Event::Reach { .. } => {\n"
        "                ensure!(cans.can_riichi, \"cannot riichi\");\n"
        "            }\n\n"
        "            Event::Chi {\n",
        "            Event::Reach { .. } => {\n"
        "                ensure!(cans.can_riichi, \"cannot riichi\");\n"
        "            }\n\n"
        "            Event::Nukidora { pai, .. } => {\n"
        "                ensure!(self.num_players == 3, \"nukidora is only legal in 3P\");\n"
        "                ensure!(cans.can_nukidora, \"cannot nukidora\");\n"
        "                ensure!(pai == t!(N), \"nukidora tile must be N, got {pai}\");\n"
        "                self.ensure_tiles_in_hand(&[pai])?;\n"
        "            }\n\n"
        "            Event::Chi {\n",
        "nukidora validation",
    )
    text = replace_once(
        text,
        "            } => {\n"
        "                ensure!((target + 1) % 4 == actor, \"chi from non-kamicha\");\n",
        "            } => {\n"
        "                ensure!(self.num_players == 4, \"chi is not legal in 3P\");\n"
        "                ensure!((target + 1) % 4 == actor, \"chi from non-kamicha\");\n",
        "3P chi validation",
    )
    return text


def patch_rankings(text: str) -> str:
    if MARKER in text:
        return text
    text = "// " + MARKER + "\n" + text
    return replace_once(
        text,
        "        Self {\n"
        "            player_by_rank,\n"
        "            rank_by_player,\n"
        "        }\n"
        "    }\n"
        "}\n\n",
        "        Self {\n"
        "            player_by_rank,\n"
        "            rank_by_player,\n"
        "        }\n"
        "    }\n\n"
        "    /// Compute rankings for the first `n` active players while keeping\n"
        "    /// the fixed four-slot storage used by the rest of libriichi.\n"
        "    pub fn new_n(scores: &[i32; 4], n: usize) -> Self {\n"
        "        assert!(matches!(n, 3 | 4), \"expected 3 or 4 players, got {n}\");\n"
        "        let mut player_by_rank = [0u8, 1, 2, 3];\n"
        "        player_by_rank[..n].sort_by_key(|&i| -scores[i as usize]);\n\n"
        "        let mut rank_by_player = [n as u8; 4];\n"
        "        for (rank, &id) in player_by_rank[..n].iter().enumerate() {\n"
        "            rank_by_player[id as usize] = rank as u8;\n"
        "        }\n\n"
        "        Self {\n"
        "            player_by_rank,\n"
        "            rank_by_player,\n"
        "        }\n"
        "    }\n"
        "}\n\n",
        "rankings new_n",
    )


def patch_update(text: str) -> str:
    if MARKER in text:
        return text
    if REQUIRES not in text:
        raise RuntimeError("Stage 3C requires Stage 3B to be applied first")
    text = "// " + MARKER + "\n" + text

    text = replace_once(
        text,
        "            Event::Chi {\n"
        "                actor,\n"
        "                pai,\n"
        "                consumed,\n"
        "                ..\n"
        "            } => self.chi(actor, pai, consumed)?,\n",
        "            Event::Chi {\n"
        "                actor,\n"
        "                pai,\n"
        "                consumed,\n"
        "                ..\n"
        "            } => {\n"
        "                ensure!(self.num_players == 4, \"chi is not legal in 3P\");\n"
        "                self.chi(actor, pai, consumed)?;\n"
        "            }\n",
        "update chi gate",
    )
    text = replace_once(
        text,
        "            Event::Ankan { actor, consumed } => self.ankan(actor, consumed)?,\n"
        "            Event::Dora { dora_marker } => self.add_dora_indicator(dora_marker)?,\n",
        "            Event::Ankan { actor, consumed } => self.ankan(actor, consumed)?,\n"
        "            Event::Nukidora { .. } => {\n"
        "                ensure!(self.num_players == 3, \"nukidora is only legal in 3P\");\n"
        "                anyhow::bail!(\"nukidora state transition is not installed yet\");\n"
        "            }\n"
        "            Event::Dora { dora_marker } => self.add_dora_indicator(dora_marker)?,\n",
        "nukidora explicit safety gate",
    )

    text = replace_once(
        text,
        "        self.bakaze = bakaze;\n"
        "        self.honba = honba;\n"
        "        self.kyotaku = kyotaku;\n"
        "        self.oya = self.rel(oya) as u8;\n"
        "        self.jikaze = must_tile!(tu8!(E) + (4 - self.oya) % 4);\n",
        "        self.bakaze = bakaze;\n"
        "        self.honba = honba;\n"
        "        self.kyotaku = kyotaku;\n"
        "        self.num_players = scores.len() as u8;\n"
        "        self.oya = self.rel(oya) as u8;\n"
        "        self.jikaze = if self.num_players == 3 {\n"
        "            must_tile!(tu8!(E) + self.oya)\n"
        "        } else {\n"
        "            must_tile!(tu8!(E) + (4 - self.oya) % 4)\n"
        "        };\n",
        "mode-aware seat wind",
    )
    text = replace_once(
        text,
        "        self.is_all_last = match self.bakaze.as_u8() {\n"
        "            tu8!(E) => false,\n"
        "            tu8!(S) => self.kyoku == 3,\n"
        "            _ => true,\n"
        "        };\n\n"
        "        self.scores.fill(0);\n"
        "        self.scores[..scores.len()].copy_from_slice(scores);\n"
        "        self.scores.rotate_left(self.player_id as usize);\n",
        "        self.is_all_last = match self.bakaze.as_u8() {\n"
        "            tu8!(E) => false,\n"
        "            tu8!(S) => self.kyoku == self.num_players - 1,\n"
        "            _ => true,\n"
        "        };\n\n"
        "        self.scores.fill(0);\n"
        "        if self.num_players == 3 {\n"
        "            for rel in 0..3 {\n"
        "                let abs = (self.player_id as usize + 3 - rel) % 3;\n"
        "                self.scores[rel] = scores[abs];\n"
        "            }\n"
        "        } else {\n"
        "            self.scores.copy_from_slice(scores);\n"
        "            self.scores.rotate_left(self.player_id as usize);\n"
        "        }\n",
        "mode-aware score rotation",
    )
    text = replace_once(
        text,
        "        self.tiles_left = 70;\n",
        "        self.tiles_left = if self.num_players == 3 { 55 } else { 70 };\n",
        "mode-aware live wall",
    )
    text = replace_once(
        text,
        "        self.last_cans.can_riichi = self.is_menzen\n"
        "            && self.tiles_left >= 4\n",
        "        self.last_cans.can_riichi = self.is_menzen\n"
        "            && self.tiles_left >= self.num_players\n",
        "mode-aware riichi live tiles",
    )
    text = replace_once(
        text,
        "        if actor_rel == 3 && !pai.is_jihai() && self.tehai_len_div3 > 0 {\n",
        "        if self.num_players == 4\n"
        "            && actor_rel == 3\n"
        "            && !pai.is_jihai()\n"
        "            && self.tehai_len_div3 > 0\n"
        "        {\n",
        "3P no chi candidate",
    )
    text = replace_once(
        text,
        "    pub(super) const fn rel(&self, actor: u8) -> usize {\n"
        "        ((actor + 4 - self.player_id) % 4) as usize\n"
        "    }\n",
        "    pub(super) const fn rel(&self, actor: u8) -> usize {\n"
        "        if self.num_players == 3 {\n"
        "            ((self.player_id + 3 - actor) % 3) as usize\n"
        "        } else {\n"
        "            ((actor + 4 - self.player_id) % 4) as usize\n"
        "        }\n"
        "    }\n",
        "mode-aware relative seat",
    )
    text = replace_once(
        text,
        "    pub(super) fn pad_kawa_for_pon_or_daiminkan(&mut self, abs_actor: u8, abs_target: u8) {\n"
        "        let mut i = (abs_target + 1) % 4;\n"
        "        while i != abs_actor {\n"
        "            let rel = self.rel(i);\n"
        "            self.kawa[rel].push(None);\n"
        "            i = (i + 1) % 4;\n"
        "        }\n"
        "    }\n",
        "    pub(super) fn pad_kawa_for_pon_or_daiminkan(&mut self, abs_actor: u8, abs_target: u8) {\n"
        "        let n = self.num_players;\n"
        "        let mut i = (abs_target + 1) % n;\n"
        "        while i != abs_actor {\n"
        "            let rel = self.rel(i);\n"
        "            self.kawa[rel].push(None);\n"
        "            i = (i + 1) % n;\n"
        "        }\n"
        "    }\n",
        "mode-aware kawa padding",
    )
    text = replace_once(
        text,
        "    pub(super) fn get_rank(&self, mut scores_rel: [i32; 4]) -> u8 {\n"
        "        let scores_abs = {\n"
        "            scores_rel.rotate_right(self.player_id as usize);\n"
        "            scores_rel\n"
        "        };\n"
        "        Rankings::new(scores_abs).rank_by_player[self.player_id as usize]\n"
        "    }\n",
        "    pub(super) fn get_rank(&self, mut scores_rel: [i32; 4]) -> u8 {\n"
        "        if self.num_players == 3 {\n"
        "            let mut scores_abs = [0; 4];\n"
        "            for rel in 0..3 {\n"
        "                let abs = (self.player_id as usize + 3 - rel) % 3;\n"
        "                scores_abs[abs] = scores_rel[rel];\n"
        "            }\n"
        "            Rankings::new_n(&scores_abs, 3).rank_by_player[self.player_id as usize]\n"
        "        } else {\n"
        "            scores_rel.rotate_right(self.player_id as usize);\n"
        "            Rankings::new(scores_rel).rank_by_player[self.player_id as usize]\n"
        "        }\n"
        "    }\n",
        "mode-aware rank",
    )
    return text


def patch_file(root: Path, rel: str, transform, *, require_stage3b: bool = False) -> None:
    path = root / rel
    if not path.is_file():
        raise RuntimeError(f"missing upstream file: {path}")
    original = path.read_text(encoding="utf-8")
    if require_stage3b and REQUIRES not in original:
        raise RuntimeError(f"{rel} does not contain required Stage 3B marker")
    expected = EXPECTED.get(rel)
    if MARKER not in original and expected is not None:
        actual = git_blob_sha(path)
        if actual != expected:
            raise RuntimeError(f"unexpected upstream {rel}: expected {expected}, got {actual}")
    updated = transform(original)
    if updated != original:
        backup = path.with_suffix(path.suffix + ".unified-stage3c.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(updated, encoding="utf-8")
        print(f"patched: {path}")
    else:
        print(f"unchanged: {path}")


def apply(root: Path) -> None:
    patch_file(root, "libriichi/src/state/player_state.rs", patch_player_state)
    patch_file(root, "libriichi/src/state/getter.rs", patch_getter)
    patch_file(root, "libriichi/src/state/action.rs", patch_action)
    patch_file(root, "libriichi/src/rankings.rs", patch_rankings)
    patch_file(root, "libriichi/src/state/update.rs", patch_update, require_stage3b=True)

    checks = {
        "libriichi/src/state/player_state.rs": "pub(super) num_players: u8",
        "libriichi/src/state/action.rs": "pub can_nukidora: bool",
        "libriichi/src/rankings.rs": "pub fn new_n",
        "libriichi/src/state/update.rs": "if self.num_players == 3",
    }
    for rel, needle in checks.items():
        text = (root / rel).read_text(encoding="utf-8")
        if MARKER not in text or needle not in text:
            raise RuntimeError(f"Stage 3C postcondition failed: {rel}: {needle}")
    print("MORTAL_UNIFIED_PLAYER_STATE_STAGE3C_OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    apply(args.root.expanduser().resolve())


if __name__ == "__main__":
    main()
