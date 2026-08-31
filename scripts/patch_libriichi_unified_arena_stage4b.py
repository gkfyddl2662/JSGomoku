from __future__ import annotations

import argparse
import shutil
from pathlib import Path


MARKER = "MORTAL_ROGS_UNIFIED_ARENA_STAGE4B"
REQUIRES = "MORTAL_ROGS_UNIFIED_ARENA_STAGE4A"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        if new in text:
            return text
        raise RuntimeError(f"{label}: anchor not found")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_board(text: str) -> str:
    if MARKER in text:
        return text
    if REQUIRES not in text:
        raise RuntimeError("Stage 4B requires unified arena Stage 4A")

    text = "// " + MARKER + "\n" + text

    text = replace_once(
        text,
        "    fn handle_hora(\n"
        "        &mut self,\n"
        "        single_actor: u8,\n"
        "        single_target: u8,\n"
        "        reactions: &[EventExt; 4],\n"
        "    ) -> Result<()> {\n"
        "        if self.num_players == 3 {\n"
        "            bail!(\"3P arena Hora scoring requires unified arena Stage 4B\");\n"
        "        }\n"
        "        self.has_hora = true;\n",
        "    fn calc_tsumo_deltas(\n"
        "        &self,\n"
        "        actor: u8,\n"
        "        point: crate::algo::point::Point,\n"
        "        kyotaku_point: i32,\n"
        "        honba: i32,\n"
        "    ) -> [i32; 4] {\n"
        "        let active = self.active_players();\n"
        "        let mut deltas = [0; 4];\n"
        "        let honba_total = honba * (active as i32 - 1) * 100;\n\n"
        "        if let Some(pao_target) = self.paos[actor as usize] {\n"
        "            deltas[pao_target as usize] = -point.ron - honba_total;\n"
        "        } else {\n"
        "            deltas[..active].fill(-point.tsumo_ko - honba * 100);\n"
        "            if actor != self.oya {\n"
        "                deltas[self.oya as usize] = -point.tsumo_oya - honba * 100;\n"
        "            }\n"
        "        }\n\n"
        "        let tsumo_total = if actor == self.oya {\n"
        "            point.tsumo_ko * (active as i32 - 1)\n"
        "        } else {\n"
        "            point.tsumo_oya + point.tsumo_ko * (active as i32 - 2)\n"
        "        };\n"
        "        deltas[actor as usize] = tsumo_total + kyotaku_point + honba_total;\n"
        "        deltas\n"
        "    }\n\n"
        "    fn handle_hora(\n"
        "        &mut self,\n"
        "        single_actor: u8,\n"
        "        single_target: u8,\n"
        "        reactions: &[EventExt; 4],\n"
        "    ) -> Result<()> {\n"
        "        self.has_hora = true;\n",
        "install common tsumo scoring helper",
    )

    text = replace_once(
        text,
        "        let points = reactions\n"
        "            .iter()\n"
        "            .map(|ev| match ev.event {\n",
        "        let points = reactions\n"
        "            .iter()\n"
        "            .take(self.active_players())\n"
        "            .map(|ev| match ev.event {\n",
        "active hora reactions",
    )

    text = replace_once(
        text,
        "                .skip(single_target as usize + 1)\n"
        "                .take(3)\n",
        "                .skip(single_target as usize + 1)\n"
        "                .take(self.active_players() - 1)\n",
        "mode-aware multi-ron order",
    )

    text = replace_once(
        text,
        "                        deltas: Some(deltas.to_vec()),\n",
        "                        deltas: Some(deltas[..self.active_players()].to_vec()),\n",
        "active ron deltas payload",
    )

    text = replace_once(
        text,
        "        let point = points[single_actor as usize].unwrap();\n"
        "        let mut deltas = [0; 4];\n"
        "        if let Some(pao_target) = self.paos[single_actor as usize] {\n"
        "            // For pao to happen, the agari must have at least 1 yakuman so ron\n"
        "            // point and sum of tsumo point should be equal.\n"
        "            deltas[pao_target as usize] = -point.ron - honba_left * 300;\n"
        "        } else {\n"
        "            deltas.fill(-point.tsumo_ko - honba_left * 100);\n"
        "            if single_actor != self.oya {\n"
        "                deltas[self.oya as usize] = -point.tsumo_oya - honba_left * 100;\n"
        "            }\n"
        "        };\n"
        "        deltas[single_actor as usize] =\n"
        "            point.tsumo_total(single_actor == self.oya) + kyotaku_point + honba_left * 300;\n",
        "        let point = points[single_actor as usize].unwrap();\n"
        "        let deltas = self.calc_tsumo_deltas(\n"
        "            single_actor,\n"
        "            point,\n"
        "            kyotaku_point,\n"
        "            honba_left,\n"
        "        );\n",
        "common tsumo deltas",
    )

    text = replace_once(
        text,
        "            deltas: Some(deltas.to_vec()),\n"
        "            ura_markers: Some(ura_markers),\n"
        "        };\n"
        "        self.add_log_no_meta(hora);\n",
        "            deltas: Some(deltas[..self.active_players()].to_vec()),\n"
        "            ura_markers: Some(ura_markers),\n"
        "        };\n"
        "        self.add_log_no_meta(hora);\n",
        "active tsumo deltas payload",
    )

    tests = r'''

#[cfg(test)]
mod unified_arena_stage4b_tests {
    use super::*;
    use crate::algo::point::Point;

    fn board_state_for(players: u8, oya: u8) -> BoardState {
        let mut state = Board {
            num_players: players,
            kyoku: oya,
            scores: if players == 3 {
                [35_000, 35_000, 35_000, 0]
            } else {
                [25_000; 4]
            },
            ..Default::default()
        }
        .into_state();
        state.oya = oya;
        state
    }

    #[test]
    fn unified_arena_stage4b_sanma_child_tsumo_matches_tenhou_payments() {
        let state = board_state_for(3, 0);
        let point = Point {
            ron: 4_000,
            tsumo_ko: 1_000,
            tsumo_oya: 2_000,
        };
        let deltas = state.calc_tsumo_deltas(1, point, 0, 1);
        assert_eq!(deltas, [-2_100, 3_200, -1_100, 0]);
        assert_eq!(deltas.iter().sum::<i32>(), 0);
    }

    #[test]
    fn unified_arena_stage4b_sanma_dealer_tsumo_uses_two_payments() {
        let state = board_state_for(3, 0);
        let point = Point {
            ron: 6_000,
            tsumo_ko: 2_000,
            tsumo_oya: 0,
        };
        let deltas = state.calc_tsumo_deltas(0, point, 0, 0);
        assert_eq!(deltas, [4_000, -2_000, -2_000, 0]);
        assert_eq!(deltas.iter().sum::<i32>(), 0);
    }

    #[test]
    fn unified_arena_stage4b_yonma_keeps_three_tsumo_payments() {
        let state = board_state_for(4, 0);
        let point = Point {
            ron: 4_000,
            tsumo_ko: 1_000,
            tsumo_oya: 2_000,
        };
        let deltas = state.calc_tsumo_deltas(1, point, 0, 0);
        assert_eq!(deltas, [-2_000, 4_000, -1_000, -1_000]);
        assert_eq!(deltas.iter().sum::<i32>(), 0);
    }
}
'''

    text = text.rstrip() + tests.rstrip() + "\n"
    return text


def apply(root: Path) -> None:
    path = root / "libriichi/src/arena/board.rs"
    if not path.is_file():
        raise RuntimeError(f"missing arena board: {path}")
    original = path.read_text(encoding="utf-8")
    updated = patch_board(original)
    if updated != original:
        backup = path.with_suffix(path.suffix + ".unified-stage4b.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(updated, encoding="utf-8")
        print(f"patched: {path}")
    else:
        print(f"unchanged: {path}")

    post = path.read_text(encoding="utf-8")
    required = (
        MARKER,
        "fn calc_tsumo_deltas",
        "point.tsumo_ko * (active as i32 - 1)",
        ".take(self.active_players() - 1)",
        "deltas[..self.active_players()].to_vec()",
        "unified_arena_stage4b_sanma_dealer_tsumo_uses_two_payments",
    )
    missing = [needle for needle in required if needle not in post]
    if missing:
        raise RuntimeError(f"Stage 4B postconditions failed: {missing}")
    if "3P arena Hora scoring requires unified arena Stage 4B" in post:
        raise RuntimeError("Stage 4B safety gate was not removed")
    print("MORTAL_UNIFIED_ARENA_STAGE4B_OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    apply(args.root.expanduser().resolve())


if __name__ == "__main__":
    main()
