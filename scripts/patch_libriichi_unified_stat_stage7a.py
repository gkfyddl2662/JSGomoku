from __future__ import annotations

import argparse
import shutil
from pathlib import Path


MARKER = "MORTAL_ROGS_UNIFIED_STAT_STAGE7A"
REQUIRES = "MORTAL_ROGS_UNIFIED_EVENT_BOUNDARY_STAGE3B"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        if new in text:
            return text
        raise RuntimeError(f"{label}: anchor not found")
    if text.count(old) != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {text.count(old)}")
    return text.replace(old, new, 1)


def patch_stat(text: str) -> str:
    if MARKER in text:
        return text
    if REQUIRES not in text:
        raise RuntimeError("Stage 7A requires normalized variable-length events from Stage 3B")
    text = "// " + MARKER + "\n" + text

    text = replace_once(
        text,
        "    #[pyo3(get, set)]\n    pub game: i64,\n",
        "    #[pyo3(get, set)]\n    pub game: i64,\n"
        "    #[pyo3(get, set)]\n    pub num_players: u8,\n",
        "Stat num_players",
    )

    text = replace_once(
        text,
        "                let active = scores.len().min(cur_scores.len());\n"
        "                cur_scores[..active].copy_from_slice(&scores[..active]);\n",
        "                let active = scores.len().min(cur_scores.len());\n"
        "                stat.num_players = active as u8;\n"
        "                cur_scores[..active].copy_from_slice(&scores[..active]);\n",
        "capture active player count",
    )

    text = replace_once(
        text,
        "        let rk = Rankings::new(cur_scores);\n\n"
        "        // assume the sum of scores to be 100k\n"
        "        let sum: i32 = cur_scores.iter().sum();\n"
        "        if sum < 100_000 {\n"
        "            cur_scores[rk.player_by_rank[0] as usize] += 100_000 - sum;\n"
        "        }\n\n"
        "        // assume the starting point to be 25000\n"
        "        let final_score = cur_scores[player_id as usize];\n"
        "        stat.point = final_score as i64 - 25000;\n",
        "        let n = if stat.num_players == 3 { 3 } else { 4 };\n"
        "        stat.num_players = n as u8;\n"
        "        let rk = Rankings::new_n(&cur_scores, n);\n\n"
        "        let target_total = if n == 3 { 105_000 } else { 100_000 };\n"
        "        let sum: i32 = cur_scores[..n].iter().sum();\n"
        "        if sum < target_total {\n"
        "            cur_scores[rk.player_by_rank[0] as usize] += target_total - sum;\n"
        "        }\n\n"
        "        let starting_point = if n == 3 { 35_000 } else { 25_000 };\n"
        "        let final_score = cur_scores[player_id as usize];\n"
        "        stat.point = final_score as i64 - starting_point;\n",
        "mode-aware final score normalization",
    )

    text = replace_once(
        text,
        "            self.total_pt([90, 45, 0, -135]),\n"
        "            self.avg_pt([90, 45, 0, -135]),\n",
        "            self.display_total_pt(),\n"
        "            self.display_avg_pt(),\n",
        "Display dynamic rank points",
    )

    text = replace_once(
        text,
        "impl Stat {\n"
        "    /// We do not use `add_game(&mut self)` here as `Stat` impls `Add` and `Sum` so we\n",
        "impl Stat {\n"
        "    #[inline]\n"
        "    fn active_players(&self) -> usize {\n"
        "        if self.num_players == 3 { 3 } else { 4 }\n"
        "    }\n\n"
        "    #[inline]\n"
        "    fn total_pt_slice(&self, pts: &[i64]) -> i64 {\n"
        "        let ranks = [self.rank_1, self.rank_2, self.rank_3, self.rank_4];\n"
        "        ranks[..self.active_players()]\n"
        "            .iter()\n"
        "            .zip(pts.iter())\n"
        "            .map(|(&count, &pt)| count * pt)\n"
        "            .sum()\n"
        "    }\n\n"
        "    #[inline]\n"
        "    fn avg_pt_slice(&self, pts: &[i64]) -> f64 {\n"
        "        self.total_pt_slice(pts) as f64 / self.game as f64\n"
        "    }\n\n"
        "    fn display_total_pt(&self) -> i64 {\n"
        "        if self.active_players() == 3 {\n"
        "            self.total_pt_slice(&[6, 0, -6])\n"
        "        } else {\n"
        "            self.total_pt_slice(&[90, 45, 0, -135])\n"
        "        }\n"
        "    }\n\n"
        "    fn display_avg_pt(&self) -> f64 {\n"
        "        if self.active_players() == 3 {\n"
        "            self.avg_pt_slice(&[6, 0, -6])\n"
        "        } else {\n"
        "            self.avg_pt_slice(&[90, 45, 0, -135])\n"
        "        }\n"
        "    }\n\n"
        "    /// We do not use `add_game(&mut self)` here as `Stat` impls `Add` and `Sum` so we\n",
        "Stat dynamic helpers",
    )

    text = replace_once(
        text,
        "    pub const fn total_pt(&self, pts: [i64; 4]) -> i64 {\n"
        "        self.rank_1 * pts[0] + self.rank_2 * pts[1] + self.rank_3 * pts[2] + self.rank_4 * pts[3]\n"
        "    }\n"
        "    #[inline]\n"
        "    #[must_use]\n"
        "    pub fn avg_pt(&self, pts: [i64; 4]) -> f64 {\n"
        "        self.total_pt(pts) as f64 / self.game as f64\n"
        "    }\n"
        "    #[getter]\n"
        "    #[inline]\n"
        "    #[must_use]\n"
        "    pub fn avg_rank(&self) -> f64 {\n"
        "        self.avg_pt([1, 2, 3, 4])\n"
        "    }\n",
        "    pub fn total_pt(&self, pts: Vec<i64>) -> Result<i64> {\n"
        "        let n = self.active_players();\n"
        "        if pts.len() != n {\n"
        "            bail!(\"expected {n} rank point values, got {}\", pts.len());\n"
        "        }\n"
        "        Ok(self.total_pt_slice(&pts))\n"
        "    }\n"
        "    #[inline]\n"
        "    #[must_use]\n"
        "    pub fn avg_pt(&self, pts: Vec<i64>) -> Result<f64> {\n"
        "        let n = self.active_players();\n"
        "        if pts.len() != n {\n"
        "            bail!(\"expected {n} rank point values, got {}\", pts.len());\n"
        "        }\n"
        "        Ok(self.avg_pt_slice(&pts))\n"
        "    }\n"
        "    #[getter]\n"
        "    #[inline]\n"
        "    #[must_use]\n"
        "    pub fn avg_rank(&self) -> f64 {\n"
        "        if self.active_players() == 3 {\n"
        "            self.avg_pt_slice(&[1, 2, 3])\n"
        "        } else {\n"
        "            self.avg_pt_slice(&[1, 2, 3, 4])\n"
        "        }\n"
        "    }\n",
        "Python dynamic rank points",
    )

    tests = r'''

#[cfg(test)]
mod unified_stat_stage7a_tests {
    use super::*;

    #[test]
    fn unified_stat_sanma_rank_metrics_ignore_fourth_slot() {
        let stat = Stat {
            game: 6,
            num_players: 3,
            rank_1: 3,
            rank_2: 2,
            rank_3: 1,
            rank_4: 99,
            ..Default::default()
        };
        assert_eq!(stat.total_pt_slice(&[6, 0, -6]), 12);
        assert!((stat.avg_rank() - (10.0 / 6.0)).abs() < 1e-12);
    }

    #[test]
    fn unified_stat_yonma_rank_metrics_keep_fourth_slot() {
        let stat = Stat {
            game: 4,
            num_players: 4,
            rank_1: 1,
            rank_2: 1,
            rank_3: 1,
            rank_4: 1,
            ..Default::default()
        };
        assert_eq!(stat.total_pt_slice(&[90, 45, 0, -135]), 0);
        assert!((stat.avg_rank() - 2.5).abs() < 1e-12);
    }
}
'''
    return text.rstrip() + tests.rstrip() + "\n"


def apply(root: Path) -> None:
    path = root.expanduser().resolve() / "libriichi/src/stat.rs"
    if not path.is_file():
        raise RuntimeError(f"missing stat.rs: {path}")
    original = path.read_text(encoding="utf-8")
    updated = patch_stat(original)
    if updated != original:
        backup = path.with_suffix(path.suffix + ".unified-stage7a.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(updated, encoding="utf-8")
        print(f"patched: {path}")
    else:
        print(f"unchanged: {path}")

    post = path.read_text(encoding="utf-8")
    for token in (
        MARKER,
        "pub num_players: u8",
        "Rankings::new_n(&cur_scores, n)",
        "target_total = if n == 3 { 105_000 } else { 100_000 }",
        "pub fn avg_pt(&self, pts: Vec<i64>)",
        "unified_stat_sanma_rank_metrics_ignore_fourth_slot",
    ):
        if token not in post:
            raise RuntimeError(f"Stage 7A postcondition missing: {token}")
    print("MORTAL_UNIFIED_STAT_STAGE7A_OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    apply(args.root)


if __name__ == "__main__":
    main()
