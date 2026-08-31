from __future__ import annotations

import argparse
import shutil
from pathlib import Path


MARKER = "MORTAL_ROGS_UNIFIED_GRP_STAGE6A"
REQUIRES = "MORTAL_ROGS_UNIFIED_PLAYER_STATE_STAGE3C"
EVENT_REQUIRES = "MORTAL_ROGS_UNIFIED_EVENT_BOUNDARY_STAGE3B"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        if new in text:
            return text
        raise RuntimeError(f"{label}: anchor not found")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_grp(text: str) -> str:
    if MARKER in text:
        return text
    if EVENT_REQUIRES not in text:
        raise RuntimeError("Stage 6A requires Stage 3B")
    text = "// " + MARKER + "\n" + text

    text = replace_once(
        text,
        "use crate::consts::GRP_SIZE;\n",
        "use crate::consts::{GRP_SIZE_3P, GRP_SIZE_4P};\n",
        "dynamic GRP constants",
    )

    text = replace_once(
        text,
        "pub struct Grp {\n"
        "    // [grand_kyoku, honba, kyotaku, [score[i] / 10000]] where i is player_id\n"
        "    pub feature: Array2<f64>,\n",
        "pub struct Grp {\n"
        "    pub num_players: u8,\n"
        "    // [grand_kyoku, honba, kyotaku, [score[i] / 10000]] where i is player_id\n"
        "    pub feature: Array2<f64>,\n",
        "Grp num_players field",
    )

    text = replace_once(
        text,
        "    /// Returns List[List[np.ndarray]]\n"
        "    pub fn take_feature<'py>(&mut self, py: Python<'py>) -> Bound<'py, PyArray2<f64>> {\n",
        "    pub const fn get_num_players(&self) -> u8 {\n"
        "        self.num_players\n"
        "    }\n\n"
        "    /// Returns List[List[np.ndarray]]\n"
        "    pub fn take_feature<'py>(&mut self, py: Python<'py>) -> Bound<'py, PyArray2<f64>> {\n",
        "Grp player count API",
    )

    text = replace_once(
        text,
        "        let mut game_info = vec![];\n"
        "        let mut rank_by_player_opt = None;\n"
        "        let mut final_deltas = [0; 4];\n"
        "        let mut final_scores = [0; 4];\n",
        "        let mut game_info = vec![];\n"
        "        let mut rank_by_player_opt = None;\n"
        "        let mut num_players_opt = None;\n"
        "        let mut final_deltas = [0; 4];\n"
        "        let mut final_scores = [0; 4];\n",
        "GRP mode state",
    )

    old_start = '''                Event::StartKyoku {
                    bakaze,
                    kyoku,
                    honba,
                    kyotaku,
                    ref scores,
                    ..
                } => {
                    if rank_by_player_opt.is_none() {
                        final_scores.fill(0);
                        let active = scores.len().min(final_scores.len());
                        final_scores[..active].copy_from_slice(&scores[..active]);
                        vec_add_assign(&mut final_scores, &final_deltas);

                        let rk = Rankings::new(final_scores);

                        // assume the sum of scores to be 100k
                        let sum: i32 = final_scores.iter().sum();
                        if sum < 100_000 {
                            final_scores[rk.player_by_rank[0] as usize] += 100_000 - sum;
                        }

                        rank_by_player_opt = Some(rk.rank_by_player);
                    }

                    let mut kyoku_info = array_vec!([_; GRP_SIZE]);
                    let grand_kyoku = match bakaze.as_u8() {
                        tu8!(E) => kyoku - 1,
                        tu8!(S) => 3 + kyoku,
                        _ => 7 + kyoku,
                    };
                    kyoku_info.push(grand_kyoku as f64);
                    kyoku_info.push(honba as f64);
                    kyoku_info.push(kyotaku as f64);
                    // assume player 0 is the oya at E1
                    kyoku_info.extend(scores.iter().map(|&score| score as f64 / 10000.));
                    assert_eq!(kyoku_info.len(), GRP_SIZE);

                    game_info.insert(0, kyoku_info);
                }
'''
    new_start = '''                Event::StartKyoku {
                    bakaze,
                    kyoku,
                    honba,
                    kyotaku,
                    ref scores,
                    ..
                } => {
                    let num_players = scores.len();
                    anyhow::ensure!(matches!(num_players, 3 | 4), "invalid GRP player count {num_players}");
                    if let Some(prev) = num_players_opt {
                        anyhow::ensure!(prev == num_players, "mixed player counts in one game: {prev} then {num_players}");
                    } else {
                        num_players_opt = Some(num_players);
                    }

                    if rank_by_player_opt.is_none() {
                        final_scores.fill(0);
                        final_scores[..num_players].copy_from_slice(scores);
                        vec_add_assign(&mut final_scores, &final_deltas);

                        let rk = Rankings::new_n(&final_scores, num_players);
                        let total_target = if num_players == 3 { 105_000 } else { 100_000 };
                        let sum: i32 = final_scores[..num_players].iter().sum();
                        if sum < total_target {
                            final_scores[rk.player_by_rank[0] as usize] += total_target - sum;
                        }

                        rank_by_player_opt = Some(rk.rank_by_player);
                    }

                    let grp_size = if num_players == 3 { GRP_SIZE_3P } else { GRP_SIZE_4P };
                    let mut kyoku_info = array_vec!([_; GRP_SIZE_4P]);
                    let n = num_players as u8;
                    let grand_kyoku = match bakaze.as_u8() {
                        tu8!(E) => kyoku - 1,
                        tu8!(S) => (n - 1) + kyoku,
                        _ => (2 * n - 1) + kyoku,
                    };
                    kyoku_info.push(grand_kyoku as f64);
                    kyoku_info.push(honba as f64);
                    kyoku_info.push(kyotaku as f64);
                    // assume player 0 is the oya at E1
                    kyoku_info.extend(scores.iter().map(|&score| score as f64 / 10000.));
                    assert_eq!(kyoku_info.len(), grp_size);

                    game_info.insert(0, kyoku_info);
                }
'''
    text = replace_once(text, old_start, new_start, "mode-aware GRP StartKyoku")

    text = replace_once(
        text,
        "        let rank_by_player =\n"
        "            rank_by_player_opt.context(\"invalid log: no Hora or Ryukyoku after a StartKyoku\")?;\n"
        "        let shape = (game_info.len(), GRP_SIZE);\n"
        "        let feature =\n"
        "            Array::from_iter(game_info.into_iter().flatten()).into_shape_with_order(shape)?;\n\n"
        "        Ok(Self {\n"
        "            feature,\n"
        "            rank_by_player,\n"
        "            final_scores,\n"
        "        })\n",
        "        let rank_by_player =\n"
        "            rank_by_player_opt.context(\"invalid log: no Hora or Ryukyoku after a StartKyoku\")?;\n"
        "        let num_players = num_players_opt.context(\"invalid log: no StartKyoku\")?;\n"
        "        let grp_size = if num_players == 3 { GRP_SIZE_3P } else { GRP_SIZE_4P };\n"
        "        let shape = (game_info.len(), grp_size);\n"
        "        let feature =\n"
        "            Array::from_iter(game_info.into_iter().flatten()).into_shape_with_order(shape)?;\n\n"
        "        Ok(Self {\n"
        "            num_players: num_players as u8,\n"
        "            feature,\n"
        "            rank_by_player,\n"
        "            final_scores,\n"
        "        })\n",
        "dynamic GRP output shape",
    )

    tests = r'''

#[cfg(test)]
mod unified_grp_stage6a_tests {
    use super::*;
    use crate::t;

    fn start(num_players: usize) -> Event {
        let score = if num_players == 3 { 35_000 } else { 25_000 };
        Event::StartKyoku {
            bakaze: t!(E),
            dora_marker: t!(1p),
            kyoku: 1,
            honba: 0,
            kyotaku: 0,
            oya: 0,
            scores: vec![score; num_players],
            tehais: vec![vec![t!(?); 13]; num_players],
        }
    }

    #[test]
    fn unified_grp_sanma_is_six_wide_and_105k() {
        let events = [
            start(3),
            Event::Ryukyoku {
                deltas: Some(vec![1_000, -1_000, 0]),
            },
        ];
        let grp = Grp::load_events(&events).unwrap();
        assert_eq!(grp.num_players, 3);
        assert_eq!(grp.feature.dim(), (1, 6));
        assert_eq!(grp.final_scores, [36_000, 34_000, 35_000, 0]);
        assert_eq!(grp.final_scores[..3].iter().sum::<i32>(), 105_000);
        assert_eq!(grp.rank_by_player[3], 3);
    }

    #[test]
    fn unified_grp_yonma_stays_seven_wide_and_100k() {
        let events = [
            start(4),
            Event::Ryukyoku {
                deltas: Some(vec![1_000, -1_000, 0, 0]),
            },
        ];
        let grp = Grp::load_events(&events).unwrap();
        assert_eq!(grp.num_players, 4);
        assert_eq!(grp.feature.dim(), (1, 7));
        assert_eq!(grp.final_scores.iter().sum::<i32>(), 100_000);
    }
}
'''
    return text.rstrip() + tests.rstrip() + "\n"


def apply(root: Path) -> None:
    rankings = root / "libriichi/src/rankings.rs"
    if not rankings.is_file() or REQUIRES not in rankings.read_text(encoding="utf-8"):
        raise RuntimeError("Stage 6A requires Stage 3C rankings")

    path = root / "libriichi/src/dataset/grp.rs"
    if not path.is_file():
        raise RuntimeError(f"missing GRP dataset source: {path}")
    original = path.read_text(encoding="utf-8")
    updated = patch_grp(original)
    if updated != original:
        backup = path.with_suffix(path.suffix + ".unified-stage6a.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(updated, encoding="utf-8")
        print(f"patched: {path}")
    else:
        print(f"unchanged: {path}")

    post = path.read_text(encoding="utf-8")
    required = (
        MARKER,
        "pub num_players: u8",
        "GRP_SIZE_3P",
        "GRP_SIZE_4P",
        "Rankings::new_n",
        "105_000",
        "unified_grp_sanma_is_six_wide_and_105k",
    )
    missing = [x for x in required if x not in post]
    if missing:
        raise RuntimeError(f"Stage 6A postconditions failed: {missing}")
    print("MORTAL_UNIFIED_GRP_STAGE6A_OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    apply(args.root.expanduser().resolve())


if __name__ == "__main__":
    main()
