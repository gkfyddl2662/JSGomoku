from __future__ import annotations

import argparse
import shutil
from pathlib import Path


MARKER = "MORTAL_ROGS_UNIFIED_GAME_STAGE5A"
BOARD_REQUIRES = "MORTAL_ROGS_UNIFIED_ARENA_STAGE4C"
RESULT_REQUIRES = "MORTAL_ROGS_UNIFIED_EVENT_BOUNDARY_STAGE3B"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        if new in text:
            return text
        raise RuntimeError(f"{label}: anchor not found")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_game(text: str) -> str:
    if MARKER in text:
        return text
    text = "// " + MARKER + "\n" + text

    text = replace_once(
        text,
        "pub struct BatchGame {\n"
        "    /// 8 for hanchan and 4 for tonpuu\n"
        "    pub length: u8,\n"
        "    pub init_scores: [i32; 4],\n"
        "    pub disable_progress_bar: bool,\n"
        "}\n",
        "pub struct BatchGame {\n"
        "    /// 8/4 for yonma hanchan/tonpuu, 6/3 for sanma.\n"
        "    pub length: u8,\n"
        "    pub num_players: u8,\n"
        "    pub target_score: i32,\n"
        "    pub init_scores: [i32; 4],\n"
        "    pub disable_progress_bar: bool,\n"
        "}\n",
        "BatchGame mode fields",
    )

    text = replace_once(
        text,
        "struct Game {\n"
        "    length: u8,\n"
        "    seed: (u64, u64),\n",
        "struct Game {\n"
        "    length: u8,\n"
        "    num_players: u8,\n"
        "    target_score: i32,\n"
        "    seed: (u64, u64),\n",
        "Game mode fields",
    )

    text = replace_once(
        text,
        "impl Game {\n    /// Returns iff any player in the game can act or the game has ended.\n",
        "impl Game {\n"
        "    #[inline]\n"
        "    const fn active_players(&self) -> usize {\n"
        "        self.num_players as usize\n"
        "    }\n\n"
        "    /// Returns iff any player in the game can act or the game has ended.\n",
        "Game active players helper",
    )

    text = replace_once(
        text,
        "            if self.kyoku >= self.length + 4\n"
        "                || self.kyoku >= self.length\n"
        "                    && !self.in_renchan\n"
        "                    && self.scores.iter().any(|&s| s >= 30000)\n",
        "            if self.kyoku >= self.length + self.num_players\n"
        "                || self.kyoku >= self.length\n"
        "                    && !self.in_renchan\n"
        "                    && self.scores[..self.active_players()]\n"
        "                        .iter()\n"
        "                        .any(|&s| s >= self.target_score)\n",
        "mode-aware game end window",
    )

    text = replace_once(
        text,
        "            let mut next_board = Board {\n"
        "                kyoku: self.kyoku,\n"
        "                honba: self.honba,\n"
        "                kyotaku: self.kyotaku,\n"
        "                scores: self.scores,\n",
        "            let mut next_board = Board {\n"
        "                kyoku: self.kyoku,\n"
        "                honba: self.honba,\n"
        "                kyotaku: self.kyotaku,\n"
        "                num_players: self.num_players,\n"
        "                scores: self.scores,\n",
        "pass mode to Board",
    )

    text = replace_once(
        text,
        "                for (player_id, state) in ctx.player_states.iter().enumerate() {\n",
        "                for (player_id, state) in ctx.player_states[..self.active_players()]\n"
        "                    .iter()\n"
        "                    .enumerate()\n"
        "                {\n",
        "active set_scene loop",
    )

    text = replace_once(
        text,
        "                for idx in &self.indexes {\n"
        "                    agents[idx.agent_idx].end_kyoku(idx.player_id_idx)?;\n"
        "                }\n",
        "                for idx in &self.indexes[..self.active_players()] {\n"
        "                    agents[idx.agent_idx].end_kyoku(idx.player_id_idx)?;\n"
        "                }\n",
        "active end_kyoku loop",
    )

    text = replace_once(
        text,
        "                let has_tobi = self.scores.iter().any(|&s| s < 0);\n",
        "                let has_tobi = self.scores[..self.active_players()]\n"
        "                    .iter()\n"
        "                    .any(|&s| s < 0);\n",
        "active tobi scan",
    )

    text = replace_once(
        text,
        "                let oya = kyoku_result.kyoku as usize % 4;\n"
        "                if kyoku_result.kyoku >= self.length - 1 && self.scores[oya] >= 30000 {\n"
        "                    let top = kyoku_result\n"
        "                        .scores\n"
        "                        .iter()\n",
        "                let oya = kyoku_result.kyoku as usize % self.active_players();\n"
        "                if kyoku_result.kyoku >= self.length - 1\n"
        "                    && self.scores[oya] >= self.target_score\n"
        "                {\n"
        "                    let top = kyoku_result\n"
        "                        .scores[..self.active_players()]\n"
        "                        .iter()\n",
        "mode-aware renchan owari",
    )

    text = replace_once(
        text,
        "            if self.kyotaku > 0 {\n"
        "                *self.scores.iter_mut().min_by_key(|s| -**s).unwrap() += self.kyotaku as i32 * 1000;\n"
        "            }\n\n"
        "            let names = array::from_fn(|i| agents[self.indexes[i].agent_idx].name());\n"
        "            let game_result = GameResult {\n"
        "                names,\n"
        "                scores: self.scores,\n",
        "            if self.kyotaku > 0 {\n"
        "                *self.scores[..self.active_players()]\n"
        "                    .iter_mut()\n"
        "                    .min_by_key(|s| -**s)\n"
        "                    .unwrap() += self.kyotaku as i32 * 1000;\n"
        "            }\n\n"
        "            let mut names: [String; 4] = array::from_fn(|_| String::new());\n"
        "            for (i, name) in names[..self.active_players()].iter_mut().enumerate() {\n"
        "                *name = agents[self.indexes[i].agent_idx].name();\n"
        "            }\n"
        "            let game_result = GameResult {\n"
        "                num_players: self.num_players,\n"
        "                names,\n"
        "                scores: self.scores,\n",
        "active GameResult construction",
    )

    text = replace_once(
        text,
        "            for idx in &self.indexes {\n"
        "                agents[idx.agent_idx].end_game(idx.player_id_idx, &game_result)?;\n"
        "            }\n",
        "            for idx in &self.indexes[..self.active_players()] {\n"
        "                agents[idx.agent_idx].end_game(idx.player_id_idx, &game_result)?;\n"
        "            }\n",
        "active end_game loop",
    )

    text = replace_once(
        text,
        "        let ctx = self.board.agent_context();\n"
        "        for (player_id, state) in ctx.player_states.iter().enumerate() {\n",
        "        let ctx = self.board.agent_context();\n"
        "        for (player_id, state) in ctx.player_states[..self.active_players()]\n"
        "            .iter()\n"
        "            .enumerate()\n"
        "        {\n",
        "active reaction commit loop",
    )

    text = replace_once(
        text,
        "    pub const fn tenhou_hanchan(disable_progress_bar: bool) -> Self {\n"
        "        Self {\n"
        "            length: 8,\n"
        "            init_scores: [25000; 4],\n"
        "            disable_progress_bar,\n"
        "        }\n"
        "    }\n",
        "    pub const fn tenhou_hanchan(disable_progress_bar: bool) -> Self {\n"
        "        Self {\n"
        "            length: 8,\n"
        "            num_players: 4,\n"
        "            target_score: 30_000,\n"
        "            init_scores: [25_000; 4],\n"
        "            disable_progress_bar,\n"
        "        }\n"
        "    }\n\n"
        "    pub const fn tenhou_sanma_hanchan(disable_progress_bar: bool) -> Self {\n"
        "        Self {\n"
        "            length: 6,\n"
        "            num_players: 3,\n"
        "            target_score: 40_000,\n"
        "            init_scores: [35_000, 35_000, 35_000, 0],\n"
        "            disable_progress_bar,\n"
        "        }\n"
        "    }\n",
        "BatchGame constructors",
    )

    text = replace_once(
        text,
        "        ensure!(!agents.is_empty());\n"
        "        ensure!(!indexes.is_empty());\n",
        "        ensure!(!agents.is_empty());\n"
        "        ensure!(!indexes.is_empty());\n"
        "        ensure!(matches!(self.num_players, 3 | 4));\n"
        "        ensure!(self.length >= self.num_players);\n",
        "BatchGame mode validation",
    )

    text = replace_once(
        text,
        "                let mut oracle_obs_versions = [None; 4];\n"
        "                for (i, idx) in idxs.iter().enumerate() {\n",
        "                let mut oracle_obs_versions = [None; 4];\n"
        "                for (i, idx) in idxs.iter().take(self.num_players as usize).enumerate() {\n",
        "active start_game loop",
    )

    text = replace_once(
        text,
        "                let game = Box::new(Game {\n"
        "                    length: self.length,\n"
        "                    seed,\n",
        "                let game = Box::new(Game {\n"
        "                    length: self.length,\n"
        "                    num_players: self.num_players,\n"
        "                    target_score: self.target_score,\n"
        "                    seed,\n",
        "Game mode initialization",
    )

    tests = r'''

    #[test]
    fn unified_sanma_batch_game_configuration() {
        let g = BatchGame::tenhou_sanma_hanchan(true);
        assert_eq!(g.num_players, 3);
        assert_eq!(g.length, 6);
        assert_eq!(g.target_score, 40_000);
        assert_eq!(g.init_scores, [35_000, 35_000, 35_000, 0]);
    }

    #[test]
    fn unified_sanma_tsumogiri_game_smoke() {
        let g = BatchGame::tenhou_sanma_hanchan(true);
        let mut agents = [
            Box::new(Tsumogiri::new_batched(&[0, 1, 2]).unwrap()) as Box<dyn BatchAgent>,
        ];
        let indexes = [[
            Index { agent_idx: 0, player_id_idx: 0 },
            Index { agent_idx: 0, player_id_idx: 1 },
            Index { agent_idx: 0, player_id_idx: 2 },
            Index::default(),
        ]];
        let results = g.run(&mut agents, &indexes, &[(20260830, 5)]).unwrap();
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].num_players, 3);
        assert_eq!(results[0].scores[3], 0);
        assert_eq!(results[0].names[3], "");
        let ranking = results[0].rankings();
        assert_eq!(ranking.rank_by_player[3], 3);
        assert!(!results[0].game_log.is_empty());
    }
'''
    text = text.replace(
        "        g.run(&mut agents, indexes, &[(1009, 0), (1021, 0)])\n            .unwrap();\n    }\n}",
        "        g.run(&mut agents, indexes, &[(1009, 0), (1021, 0)])\n            .unwrap();\n    }" + tests + "\n}",
    )
    return text


def patch_result(text: str) -> str:
    if MARKER in text:
        return text
    if RESULT_REQUIRES not in text:
        raise RuntimeError("Stage 5A expects Stage 3B result event normalization")
    text = "// " + MARKER + "\n" + text

    text = replace_once(
        text,
        "#[derive(Debug, Clone, Default)]\n"
        "pub struct GameResult {\n"
        "    pub names: [String; 4],\n",
        "#[derive(Debug, Clone, Default)]\n"
        "pub struct GameResult {\n"
        "    pub num_players: u8,\n"
        "    pub names: [String; 4],\n",
        "GameResult num_players",
    )

    text = replace_once(
        text,
        "    pub fn rankings(&self) -> Rankings {\n"
        "        Rankings::new(self.scores)\n"
        "    }\n",
        "    pub fn rankings(&self) -> Rankings {\n"
        "        let n = if self.num_players == 3 { 3 } else { 4 };\n"
        "        Rankings::new_n(&self.scores, n)\n"
        "    }\n",
        "mode-aware GameResult rankings",
    )

    text = replace_once(
        text,
        "        let start_game = Event::StartGame {\n"
        "            names: self.names.to_vec(),\n",
        "        let n = if self.num_players == 3 { 3 } else { 4 };\n"
        "        let start_game = Event::StartGame {\n"
        "            names: self.names[..n].to_vec(),\n",
        "active StartGame names",
    )
    return text


def patch_file(path: Path, transform, prerequisite: str | None = None) -> None:
    if not path.is_file():
        raise RuntimeError(f"missing file: {path}")
    original = path.read_text(encoding="utf-8")
    if prerequisite and prerequisite not in original:
        raise RuntimeError(f"missing prerequisite {prerequisite} in {path}")
    updated = transform(original)
    if updated != original:
        backup = path.with_suffix(path.suffix + ".unified-stage5a.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(updated, encoding="utf-8")
        print(f"patched: {path}")
    else:
        print(f"unchanged: {path}")


def apply(root: Path) -> None:
    board = root / "libriichi/src/arena/board.rs"
    if not board.is_file() or BOARD_REQUIRES not in board.read_text(encoding="utf-8"):
        raise RuntimeError("Stage 5A requires unified arena Stage 4C")

    game = root / "libriichi/src/arena/game.rs"
    result = root / "libriichi/src/arena/result.rs"
    patch_file(game, patch_game)
    patch_file(result, patch_result, RESULT_REQUIRES)

    game_text = game.read_text(encoding="utf-8")
    result_text = result.read_text(encoding="utf-8")
    required_game = (
        MARKER,
        "pub num_players: u8",
        "pub target_score: i32",
        "tenhou_sanma_hanchan",
        "self.scores[..self.active_players()]",
        "unified_sanma_tsumogiri_game_smoke",
    )
    required_result = (
        MARKER,
        "pub num_players: u8",
        "Rankings::new_n",
        "self.names[..n].to_vec()",
    )
    missing = [x for x in required_game if x not in game_text]
    missing += [x for x in required_result if x not in result_text]
    if missing:
        raise RuntimeError(f"Stage 5A postconditions failed: {missing}")
    print("MORTAL_UNIFIED_GAME_STAGE5A_OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    apply(args.root.expanduser().resolve())


if __name__ == "__main__":
    main()
