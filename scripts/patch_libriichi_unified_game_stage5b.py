from __future__ import annotations

import argparse
import shutil
from pathlib import Path


MARKER = "MORTAL_ROGS_UNIFIED_GAME_STAGE5B"
REQUIRES = "MORTAL_ROGS_UNIFIED_GAME_STAGE5A"

ONE_VS_TWO = r'''use super::game::{BatchGame, Index};
use super::result::GameResult;
use crate::agent::{BatchAgent, new_py_agent};
use std::fs::{self, File};
use std::io;
use std::iter;
use std::path::PathBuf;
use std::time::Duration;

use anyhow::Result;
use flate2::Compression;
use flate2::read::GzEncoder;
use indicatif::{ParallelProgressIterator, ProgressBar, ProgressStyle};
use pyo3::prelude::*;
use rayon::prelude::*;

// MORTAL_ROGS_UNIFIED_GAME_STAGE5B
#[pyclass]
#[derive(Clone, Default)]
pub struct OneVsTwo {
    pub disable_progress_bar: bool,
    pub log_dir: Option<String>,
}

#[pymethods]
impl OneVsTwo {
    #[new]
    #[pyo3(signature = (*, disable_progress_bar=false, log_dir=None))]
    const fn new(disable_progress_bar: bool, log_dir: Option<String>) -> Self {
        Self {
            disable_progress_bar,
            log_dir,
        }
    }

    /// Returns challenger finish counts [1st, 2nd, 3rd].
    pub fn py_vs_py(
        &self,
        challenger: PyObject,
        champion: PyObject,
        seed_start: (u64, u64),
        seed_count: u64,
        py: Python<'_>,
    ) -> Result<[i32; 3]> {
        py.allow_threads(move || {
            let results = self.run_batch(
                |player_ids| new_py_agent(challenger, player_ids),
                |player_ids| new_py_agent(champion, player_ids),
                seed_start,
                seed_count,
            )?;

            let mut rankings = [0; 3];
            for (i, result) in results.iter().enumerate() {
                let rank = result.rankings().rank_by_player[i % 3];
                rankings[rank as usize] += 1;
            }
            Ok(rankings)
        })
    }
}

impl OneVsTwo {
    pub fn run_batch<C, M>(
        &self,
        new_challenger_agent: C,
        new_champion_agent: M,
        seed_start: (u64, u64),
        seed_count: u64,
    ) -> Result<Vec<GameResult>>
    where
        C: FnOnce(&[u8]) -> Result<Box<dyn BatchAgent>>,
        M: FnOnce(&[u8]) -> Result<Box<dyn BatchAgent>>,
    {
        if let Some(dir) = &self.log_dir {
            fs::create_dir_all(dir)?;
        }

        log::info!(
            "sanma seed: [{}, {}) w/ {:#x}, {} sets, {} hanchans",
            seed_start.0,
            seed_start.0 + seed_count,
            seed_start.1,
            seed_count,
            seed_count * 3,
        );

        let seeds: Vec<_> = (seed_start.0..seed_start.0 + seed_count)
            .flat_map(|seed| iter::repeat_n((seed, seed_start.1), 3))
            .collect();

        let challenger_player_ids: Vec<_> = (0..3)
            .cycle()
            .take(seed_count as usize * 3)
            .collect();

        let champion_player_ids_per_seed = [
            1, 2,
            0, 2,
            0, 1,
        ];
        let champion_player_ids: Vec<_> = champion_player_ids_per_seed
            .into_iter()
            .cycle()
            .take(seed_count as usize * champion_player_ids_per_seed.len())
            .collect();

        let mut agents = [
            new_challenger_agent(&challenger_player_ids)?,
            new_champion_agent(&champion_player_ids)?,
        ];
        let batch_game = BatchGame::tenhou_sanma_hanchan(self.disable_progress_bar);

        let mut challenger_idx = 0;
        let mut champion_idx = 0;
        let agent_idxs_per_seed = [
            [0, 1, 1],
            [1, 0, 1],
            [1, 1, 0],
        ];
        let indexes: Vec<[Index; 4]> = agent_idxs_per_seed
            .into_iter()
            .cycle()
            .take(seed_count as usize * agent_idxs_per_seed.len())
            .map(|split| {
                let mut out = [Index::default(); 4];
                for (seat, agent_idx) in split.into_iter().enumerate() {
                    let player_id_idx = if agent_idx == 0 {
                        &mut challenger_idx
                    } else {
                        &mut champion_idx
                    };
                    out[seat] = Index {
                        agent_idx,
                        player_id_idx: *player_id_idx,
                    };
                    *player_id_idx += 1;
                }
                out
            })
            .collect();

        let results = batch_game.run(&mut agents, &indexes, &seeds)?;

        if let Some(dir) = &self.log_dir {
            log::info!("dumping sanma game logs");
            let bar = if self.disable_progress_bar {
                ProgressBar::hidden()
            } else {
                ProgressBar::new(seed_count * 3)
            };
            const TEMPLATE: &str = "[{elapsed_precise}] [{wide_bar}] {pos}/{len} {percent:>3}%";
            bar.set_style(ProgressStyle::with_template(TEMPLATE)?.progress_chars("#-"));
            bar.enable_steady_tick(Duration::from_millis(150));

            results
                .par_iter()
                .progress_with(bar)
                .enumerate()
                .try_for_each(|(i, game_result)| {
                    let split_name = ["a", "b", "c"][i % 3];
                    let (seed, key) = game_result.seed;
                    let filename: PathBuf = [dir, &format!("{seed}_{key}_{split_name}.json.gz")]
                        .iter()
                        .collect();
                    let log = game_result.dump_json_log()?;
                    let mut comp = GzEncoder::new(log.as_bytes(), Compression::best());
                    let mut f = File::create(filename)?;
                    io::copy(&mut comp, &mut f)?;
                    anyhow::Ok(())
                })?;
        }

        Ok(results)
    }
}

#[cfg(test)]
mod unified_one_vs_two_tests {
    use super::*;
    use crate::agent::Tsumogiri;

    #[test]
    fn unified_one_vs_two_rotates_all_three_challenger_seats() {
        let arena = OneVsTwo {
            disable_progress_bar: true,
            log_dir: None,
        };
        let results = arena
            .run_batch(
                |ids| Tsumogiri::new_batched(ids).map(|a| Box::new(a) as Box<dyn BatchAgent>),
                |ids| Tsumogiri::new_batched(ids).map(|a| Box::new(a) as Box<dyn BatchAgent>),
                (20260830, 9),
                1,
            )
            .unwrap();
        assert_eq!(results.len(), 3);
        assert!(results.iter().all(|r| r.num_players == 3));
        assert!(results.iter().all(|r| r.scores[3] == 0));
        for (i, result) in results.iter().enumerate() {
            let rank = result.rankings().rank_by_player[i % 3];
            assert!(rank < 3);
        }
    }
}
'''


def patch_mod(text: str) -> str:
    if MARKER in text:
        return text
    text = text.replace("mod one_vs_three;\n", "mod one_vs_three;\nmod one_vs_two;\n", 1)
    text = text.replace("use one_vs_three::OneVsThree;\n", "use one_vs_three::OneVsThree;\nuse one_vs_two::OneVsTwo;\n", 1)
    text = text.replace(
        "    m.add_class::<OneVsThree>()?;\n",
        "    m.add_class::<OneVsThree>()?;\n    m.add_class::<OneVsTwo>()?;\n",
        1,
    )
    return "// " + MARKER + "\n" + text


def apply(root: Path) -> None:
    game = root / "libriichi/src/arena/game.rs"
    if not game.is_file() or REQUIRES not in game.read_text(encoding="utf-8"):
        raise RuntimeError("Stage 5B requires Stage 5A")

    one_vs_two = root / "libriichi/src/arena/one_vs_two.rs"
    if one_vs_two.exists():
        existing = one_vs_two.read_text(encoding="utf-8")
        if MARKER not in existing:
            raise RuntimeError(f"refusing to overwrite unexpected {one_vs_two}")
        print(f"unchanged: {one_vs_two}")
    else:
        one_vs_two.write_text(ONE_VS_TWO, encoding="utf-8")
        print(f"created: {one_vs_two}")

    mod = root / "libriichi/src/arena/mod.rs"
    original = mod.read_text(encoding="utf-8")
    updated = patch_mod(original)
    if updated != original:
        backup = mod.with_suffix(mod.suffix + ".unified-stage5b.bak")
        if not backup.exists():
            shutil.copy2(mod, backup)
        mod.write_text(updated, encoding="utf-8")
        print(f"patched: {mod}")

    mod_text = mod.read_text(encoding="utf-8")
    wrapper_text = one_vs_two.read_text(encoding="utf-8")
    required = (
        "mod one_vs_two;",
        "use one_vs_two::OneVsTwo;",
        "m.add_class::<OneVsTwo>()?;",
    )
    missing = [x for x in required if x not in mod_text]
    missing += [
        x
        for x in (
            MARKER,
            "BatchGame::tenhou_sanma_hanchan",
            "let indexes: Vec<[Index; 4]>",
            "Result<[i32; 3]>",
            "unified_one_vs_two_rotates_all_three_challenger_seats",
        )
        if x not in wrapper_text
    ]
    if missing:
        raise RuntimeError(f"Stage 5B postconditions failed: {missing}")
    print("MORTAL_UNIFIED_GAME_STAGE5B_OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    apply(args.root.expanduser().resolve())


if __name__ == "__main__":
    main()
