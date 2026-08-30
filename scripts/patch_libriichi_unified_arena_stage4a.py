from __future__ import annotations

import argparse
import shutil
from pathlib import Path


MARKER = "MORTAL_ROGS_UNIFIED_ARENA_STAGE4A"
REQUIRES = "MORTAL_ROGS_UNIFIED_EVENT_BOUNDARY_STAGE3B"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        if new in text:
            return text
        raise RuntimeError(f"{label}: anchor not found")
    if text.count(old) != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {text.count(old)}")
    return text.replace(old, new, 1)


def patch_board(text: str) -> str:
    if MARKER in text:
        return text
    if REQUIRES not in text:
        raise RuntimeError("Stage 4A requires unified event boundary Stage 3B")

    text = "// " + MARKER + "\n" + text

    text = replace_once(
        text,
        "    /// Does not effect the kyoku seed\n"
        "    pub kyotaku: u8,\n"
        "    /// [25000; 4]\n",
        "    /// Does not effect the kyoku seed\n"
        "    pub kyotaku: u8,\n"
        "    /// 0/4 = yonma, 3 = sanma. Zero keeps stock Default behavior.\n"
        "    pub num_players: u8,\n"
        "    /// Active scores occupy the first num_players slots.\n",
        "Board num_players field",
    )

    text = replace_once(
        text,
        "pub struct BoardState {\n    board: Board,\n",
        "pub struct BoardState {\n    board: Board,\n    num_players: u8,\n",
        "BoardState num_players field",
    )

    text = replace_once(
        text,
        "impl Board {\n    pub fn init_from_seed(&mut self, game_seed: (u64, u64)) {\n",
        "impl Board {\n"
        "    #[inline]\n"
        "    pub const fn active_players(&self) -> usize {\n"
        "        if self.num_players == 3 { 3 } else { 4 }\n"
        "    }\n\n"
        "    pub fn init_from_seed(&mut self, game_seed: (u64, u64)) {\n"
        "        let num_players = self.active_players();\n",
        "Board active player helper",
    )

    text = replace_once(
        text,
        "        let mut rng = ChaCha12Rng::from_seed(kyoku_seed);\n"
        "        let mut seq = UNSHUFFLED;\n"
        "        seq.shuffle(&mut rng);\n\n"
        "        self.haipai = array::from_fn(|i| seq[i * 13..(i + 1) * 13].try_into().unwrap());\n"
        "        let mut idx = 13 * 4;\n\n"
        "        self.rinshan = seq[idx..idx + 4].to_vec();\n"
        "        idx += 4;\n"
        "        self.dora_indicators = seq[idx..idx + 5].to_vec();\n"
        "        idx += 5;\n"
        "        self.ura_indicators = seq[idx..idx + 5].to_vec();\n"
        "        idx += 5;\n"
        "        self.yama = seq[idx..idx + 70].to_vec();\n"
        "        idx += 70;\n"
        "        assert_eq!(idx, seq.len());\n",
        "        let mut rng = ChaCha12Rng::from_seed(kyoku_seed);\n"
        "        let mut seq = UNSHUFFLED.to_vec();\n"
        "        if num_players == 3 {\n"
        "            seq.retain(|tile| {\n"
        "                !matches_tu8!(\n"
        "                    tile.as_u8(),\n"
        "                    2m | 3m | 4m | 5m | 5mr | 6m | 7m | 8m\n"
        "                )\n"
        "            });\n"
        "        }\n"
        "        seq.shuffle(&mut rng);\n\n"
        "        self.haipai = [[t!(?); 13]; 4];\n"
        "        for (i, hand) in self.haipai.iter_mut().take(num_players).enumerate() {\n"
        "            hand.copy_from_slice(&seq[i * 13..(i + 1) * 13]);\n"
        "        }\n"
        "        let mut idx = 13 * num_players;\n\n"
        "        self.rinshan = seq[idx..idx + 4].to_vec();\n"
        "        idx += 4;\n"
        "        self.dora_indicators = seq[idx..idx + 5].to_vec();\n"
        "        idx += 5;\n"
        "        self.ura_indicators = seq[idx..idx + 5].to_vec();\n"
        "        idx += 5;\n"
        "        let live_tiles = if num_players == 3 { 55 } else { 70 };\n"
        "        self.yama = seq[idx..idx + live_tiles].to_vec();\n"
        "        idx += live_tiles;\n"
        "        assert_eq!(idx, seq.len());\n",
        "mode-aware wall creation",
    )

    text = replace_once(
        text,
        "    pub fn into_state(self) -> BoardState {\n"
        "        let oya = self.kyoku % 4;\n"
        "        let dora_indicators_full = self.dora_indicators.clone();\n\n"
        "        BoardState {\n"
        "            board: self,\n"
        "            oya,\n"
        "            player_states: array::from_fn(|i| PlayerState::new(i as u8)),\n"
        "            dora_indicators_full,\n"
        "            ..Default::default()\n"
        "        }\n"
        "    }\n",
        "    pub fn into_state(self) -> BoardState {\n"
        "        let num_players = self.active_players();\n"
        "        let oya = self.kyoku % num_players as u8;\n"
        "        let dora_indicators_full = self.dora_indicators.clone();\n\n"
        "        BoardState {\n"
        "            board: self,\n"
        "            num_players: num_players as u8,\n"
        "            oya,\n"
        "            player_states: array::from_fn(|i| PlayerState::new(i as u8)),\n"
        "            tiles_left: if num_players == 3 { 55 } else { 70 },\n"
        "            can_nagashi_mangan: if num_players == 3 {\n"
        "                [true, true, true, false]\n"
        "            } else {\n"
        "                [true; 4]\n"
        "            },\n"
        "            can_four_wind: num_players == 4,\n"
        "            dora_indicators_full,\n"
        "            ..Default::default()\n"
        "        }\n"
        "    }\n",
        "mode-aware BoardState init",
    )

    text = replace_once(
        text,
        "impl BoardState {\n    /// Returns iff any player on the board can act or the kyoku has ended.\n",
        "impl BoardState {\n"
        "    #[inline]\n"
        "    const fn active_players(&self) -> usize {\n"
        "        self.num_players as usize\n"
        "    }\n\n"
        "    #[inline]\n"
        "    const fn initial_live_tiles(&self) -> u8 {\n"
        "        if self.num_players == 3 { 55 } else { 70 }\n"
        "    }\n\n"
        "    /// Returns iff any player on the board can act or the kyoku has ended.\n",
        "BoardState active player helpers",
    )

    text = replace_once(
        text,
        "                    if self.player_states.iter().any(|c| c.last_cans().can_act()) {\n",
        "                    if self.player_states[..self.active_players()]\n"
        "                        .iter()\n"
        "                        .any(|c| c.last_cans().can_act())\n"
        "                    {\n",
        "active poll scan",
    )

    text = replace_once(
        text,
        "    fn broadcast(&mut self, ev: &Event) {\n"
        "        for s in &mut self.player_states {\n"
        "            s.update(ev).expect(\"fatal internal bug in BoardState\");\n"
        "        }\n"
        "    }\n",
        "    fn broadcast(&mut self, ev: &Event) {\n"
        "        let active = self.active_players();\n"
        "        for s in &mut self.player_states[..active] {\n"
        "            s.update(ev).expect(\"fatal internal bug in BoardState\");\n"
        "        }\n"
        "    }\n",
        "active broadcast",
    )

    text = replace_once(
        text,
        "    fn haipai(&mut self) -> Result<()> {\n"
        "        let bakaze = must_tile!(tu8!(E) + self.board.kyoku / 4);\n",
        "    fn haipai(&mut self) -> Result<()> {\n"
        "        let active = self.active_players();\n"
        "        let bakaze = must_tile!(tu8!(E) + self.board.kyoku / self.num_players);\n",
        "mode-aware bakaze",
    )

    text = replace_once(
        text,
        "            scores: self.board.scores.to_vec(),\n"
        "            tehais: self.board.haipai.iter().map(|hand| hand.to_vec()).collect(),\n",
        "            scores: self.board.scores[..active].to_vec(),\n"
        "            tehais: self.board.haipai[..active]\n"
        "                .iter()\n"
        "                .map(|hand| hand.to_vec())\n"
        "                .collect(),\n",
        "active StartKyoku payload",
    )

    # Exhaustive draw: keep the internal [4] storage but only charge active seats.
    text = replace_once(
        text,
        "        self.can_nagashi_mangan\n"
        "            .iter()\n"
        "            .enumerate()\n",
        "        self.can_nagashi_mangan[..self.active_players()]\n"
        "            .iter()\n"
        "            .enumerate()\n",
        "active nagashi scan",
    )

    text = replace_once(
        text,
        "                if i as u8 == self.oya {\n"
        "                    let mut dod = [-4000; 4];\n"
        "                    dod[i] = 12000;\n"
        "                    vec_add_assign(&mut deltas, &dod);\n"
        "                } else {\n"
        "                    let mut dod = [-2000; 4];\n"
        "                    dod[i] = 8000;\n"
        "                    dod[self.oya as usize] = -4000;\n"
        "                    vec_add_assign(&mut deltas, &dod);\n"
        "                };\n",
        "                let mut dod = [0; 4];\n"
        "                if self.num_players == 3 {\n"
        "                    for v in &mut dod[..3] {\n"
        "                        *v = if i as u8 == self.oya { -4000 } else { -2000 };\n"
        "                    }\n"
        "                    dod[i] = if i as u8 == self.oya { 8000 } else { 6000 };\n"
        "                    if i as u8 != self.oya {\n"
        "                        dod[self.oya as usize] = -4000;\n"
        "                    }\n"
        "                } else if i as u8 == self.oya {\n"
        "                    dod.fill(-4000);\n"
        "                    dod[i] = 12000;\n"
        "                } else {\n"
        "                    dod.fill(-2000);\n"
        "                    dod[i] = 8000;\n"
        "                    dod[self.oya as usize] = -4000;\n"
        "                }\n"
        "                vec_add_assign(&mut deltas, &dod);\n",
        "mode-aware nagashi payments",
    )

    text = replace_once(
        text,
        "            let tenpai_actors: ArrayVec<[_; 4]> = self\n"
        "                .player_states\n"
        "                .iter()\n",
        "            let tenpai_actors: ArrayVec<[_; 4]> = self\n"
        "                .player_states[..self.active_players()]\n"
        "                .iter()\n",
        "active tenpai scan",
    )

    text = replace_once(
        text,
        "            let (plus, minus) = match tenpai_actors.len() {\n"
        "                1 => (3000, -1000),\n"
        "                2 => (1500, -1500),\n"
        "                3 => (1000, -3000),\n"
        "                // 0 | 4\n"
        "                _ => (0, 0),\n"
        "            };\n"
        "            if plus > 0 {\n"
        "                let mut dod = [minus; 4];\n"
        "                tenpai_actors.into_iter().for_each(|i| dod[i] = plus);\n"
        "                vec_add_assign(&mut deltas, &dod);\n"
        "            }\n",
        "            let (plus, minus) = match (self.num_players, tenpai_actors.len()) {\n"
        "                (3, 1) => (2000, -1000),\n"
        "                (3, 2) => (1000, -2000),\n"
        "                (4, 1) => (3000, -1000),\n"
        "                (4, 2) => (1500, -1500),\n"
        "                (4, 3) => (1000, -3000),\n"
        "                _ => (0, 0),\n"
        "            };\n"
        "            if plus > 0 {\n"
        "                let mut dod = [0; 4];\n"
        "                dod[..self.active_players()].fill(minus);\n"
        "                tenpai_actors.into_iter().for_each(|i| dod[i] = plus);\n"
        "                vec_add_assign(&mut deltas, &dod);\n"
        "            }\n",
        "mode-aware noten payments",
    )

    text = replace_once(
        text,
        "        let ryukyoku = Event::Ryukyoku {\n"
        "            deltas: Some(deltas.to_vec()),\n"
        "        };\n",
        "        let ryukyoku = Event::Ryukyoku {\n"
        "            deltas: Some(deltas[..self.active_players()].to_vec()),\n"
        "        };\n",
        "active exhaustive deltas",
    )

    # Safety gate: scoring is installed in Stage 4B; never silently use 4P tsumo math in 3P.
    text = replace_once(
        text,
        "    fn handle_hora(\n"
        "        &mut self,\n"
        "        single_actor: u8,\n"
        "        single_target: u8,\n"
        "        reactions: &[EventExt; 4],\n"
        "    ) -> Result<()> {\n"
        "        self.has_hora = true;\n",
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
        "3P Hora score safety gate",
    )

    text = replace_once(
        text,
        "        let ryukyoku = Event::Ryukyoku {\n"
        "            deltas: Some(vec![0; 4]),\n"
        "        };\n",
        "        let ryukyoku = Event::Ryukyoku {\n"
        "            deltas: Some(vec![0; self.active_players()]),\n"
        "        };\n",
        "active abortive deltas",
    )

    text = replace_once(
        text,
        "    fn step(&mut self, reactions: &[EventExt; 4]) -> Result<Poll> {\n"
        "        if self.tiles_left == 70 {\n",
        "    fn step(&mut self, reactions: &[EventExt; 4]) -> Result<Poll> {\n"
        "        if self.tiles_left == self.initial_live_tiles() {\n",
        "mode-aware initial live wall",
    )

    text = replace_once(
        text,
        "        if self.accepted_riichis == 4 {\n"
        "            // 四家立直\n",
        "        if self.accepted_riichis == self.num_players {\n"
        "            // all active players accepted riichi\n",
        "mode-aware all-riichi abort",
    )

    text = replace_once(
        text,
        "        for (actor, ev) in reactions.iter().enumerate() {\n",
        "        for (actor, ev) in reactions.iter().take(self.active_players()).enumerate() {\n",
        "active reaction validation",
    )

    text = replace_once(
        text,
        "        let ev = reactions\n"
        "            .iter()\n"
        "            .min_by_key(|ev| match ev.event {\n",
        "        let ev = reactions\n"
        "            .iter()\n"
        "            .take(self.active_players())\n"
        "            .min_by_key(|ev| match ev.event {\n",
        "active reaction arbitration",
    )

    text = replace_once(
        text,
        "                self.tsumo_actor = (actor + 1) % 4;\n",
        "                self.tsumo_actor = (actor + 1) % self.num_players;\n",
        "mode-aware next actor",
    )

    text = replace_once(
        text,
        "                if self.kans == 4 && self.player_states.iter().all(|s| s.kans_count() < 4) {\n",
        "                if self.kans == 4\n"
        "                    && self.player_states[..self.active_players()]\n"
        "                        .iter()\n"
        "                        .all(|s| s.kans_count() < 4)\n"
        "                {\n",
        "active four-kan scan",
    )

    text = replace_once(
        text,
        "            Event::Reach { actor } => {\n",
        "            Event::Nukidora { actor, .. } => {\n"
        "                self.broadcast(&ev.event);\n"
        "                self.add_log(ev.clone());\n"
        "                // Tenhou sanma nuki replacement is a regular live-wall draw.\n"
        "                self.tsumo_actor = actor;\n"
        "            }\n\n"
        "            Event::Reach { actor } => {\n",
        "arena nukidora transition",
    )

    # Oracle layout is still stock 4P in this stage; fail loudly instead of emitting wrong teacher input.
    text = replace_once(
        text,
        "    pub fn encode_oracle_obs(&self, perspective: u8, version: u32) -> Array2<f32> {\n"
        "        let shape = oracle_obs_shape(version);\n",
        "    pub fn encode_oracle_obs(&self, perspective: u8, version: u32) -> Array2<f32> {\n"
        "        assert!(\n"
        "            self.num_players == 4,\n"
        "            \"3P arena oracle encoding requires unified arena Stage 4C\"\n"
        "        );\n"
        "        let shape = oracle_obs_shape(version);\n",
        "3P oracle safety gate",
    )

    tests = r'''

#[cfg(test)]
mod unified_arena_stage4a_tests {
    use super::*;

    #[test]
    fn unified_arena_stage4a_sanma_wall_and_active_seats() {
        let mut board = Board {
            num_players: 3,
            kyoku: 2,
            scores: [35_000, 35_000, 35_000, 0],
            ..Default::default()
        };
        board.init_from_seed((7, 11));
        assert_eq!(board.active_players(), 3);
        assert_eq!(board.yama.len(), 55);
        assert_eq!(board.rinshan.len(), 4);
        assert_eq!(board.dora_indicators.len(), 5);
        assert_eq!(board.ura_indicators.len(), 5);

        let all_tiles = board
            .haipai[..3]
            .iter()
            .flatten()
            .copied()
            .chain(board.yama.iter().copied())
            .chain(board.rinshan.iter().copied())
            .chain(board.dora_indicators.iter().copied())
            .chain(board.ura_indicators.iter().copied())
            .collect::<Vec<_>>();
        assert_eq!(all_tiles.len(), 108);
        assert!(all_tiles.iter().all(|tile| {
            !matches_tu8!(
                tile.as_u8(),
                2m | 3m | 4m | 5m | 5mr | 6m | 7m | 8m
            )
        }));

        let state = board.into_state();
        assert_eq!(state.num_players, 3);
        assert_eq!(state.oya, 2);
        assert_eq!(state.tiles_left, 55);
        assert!(!state.can_four_wind);
        assert!(!state.can_nagashi_mangan[3]);
    }

    #[test]
    fn unified_arena_stage4a_default_yonma_wall_is_unchanged() {
        let mut board = Board::default();
        board.init_from_seed((7, 11));
        assert_eq!(board.active_players(), 4);
        assert_eq!(board.yama.len(), 70);
        let all_tiles = board
            .haipai
            .iter()
            .flatten()
            .copied()
            .chain(board.yama.iter().copied())
            .chain(board.rinshan.iter().copied())
            .chain(board.dora_indicators.iter().copied())
            .chain(board.ura_indicators.iter().copied())
            .count();
        assert_eq!(all_tiles, 136);

        let state = board.into_state();
        assert_eq!(state.num_players, 4);
        assert_eq!(state.tiles_left, 70);
        assert!(state.can_four_wind);
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
        backup = path.with_suffix(path.suffix + ".unified-stage4a.bak")
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
        "pub const fn active_players",
        "let live_tiles = if num_players == 3 { 55 } else { 70 }",
        "self.tsumo_actor = (actor + 1) % self.num_players",
        "Event::Nukidora { actor, .. }",
        "3P arena Hora scoring requires unified arena Stage 4B",
        "unified_arena_stage4a_sanma_wall_and_active_seats",
    )
    missing = [needle for needle in required if needle not in post]
    if missing:
        raise RuntimeError(f"Stage 4A postconditions failed: {missing}")
    print("MORTAL_UNIFIED_ARENA_STAGE4A_OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    apply(args.root.expanduser().resolve())


if __name__ == "__main__":
    main()
