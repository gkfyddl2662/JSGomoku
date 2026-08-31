from __future__ import annotations

import argparse
import shutil
from pathlib import Path


MARKER = "MORTAL_ROGS_UNIFIED_NUKIDORA_STAGE3D"
REQUIRES = "MORTAL_ROGS_UNIFIED_PLAYER_STATE_STAGE3C"


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
    if REQUIRES not in text:
        raise RuntimeError("Stage 3D requires Stage 3C player state")
    text = "// " + MARKER + "\n" + text
    text = replace_once(
        text,
        "    pub(super) chankan_chance: Option<()>,\n\n"
        "    pub(super) can_w_riichi: bool,\n"
        "    pub(super) is_w_riichi: bool,\n",
        "    pub(super) chankan_chance: Option<()>,\n"
        "    pub(super) nukidora_ron_chance: Option<()>,\n\n"
        "    pub(super) can_w_riichi: bool,\n"
        "    pub(super) is_w_riichi: bool,\n"
        "    pub(super) nukidora_seen: bool,\n",
        "nukidora state fields",
    )
    return text


def patch_update(text: str) -> str:
    if MARKER in text:
        return text
    if REQUIRES not in text:
        raise RuntimeError("Stage 3D requires Stage 3C update")
    text = "// " + MARKER + "\n" + text

    text = replace_once(
        text,
        "        if self.chankan_chance.take().is_some() {\n"
        "            self.at_ippatsu = false;\n"
        "        }\n\n"
        "        match *event {\n",
        "        if self.chankan_chance.take().is_some() {\n"
        "            self.at_ippatsu = false;\n"
        "        }\n"
        "        if self.nukidora_ron_chance.take().is_some() {\n"
        "            self.at_ippatsu = false;\n"
        "        }\n\n"
        "        match *event {\n",
        "nukidora ron window cleanup",
    )
    text = replace_once(
        text,
        "            Event::Nukidora { .. } => {\n"
        "                ensure!(self.num_players == 3, \"nukidora is only legal in 3P\");\n"
        "                anyhow::bail!(\"nukidora state transition is not installed yet\");\n"
        "            }\n",
        "            Event::Nukidora { actor, pai } => {\n"
        "                ensure!(self.num_players == 3, \"nukidora is only legal in 3P\");\n"
        "                self.nukidora(actor, pai)?;\n"
        "            }\n",
        "install nukidora transition",
    )
    text = replace_once(
        text,
        "        self.ankan_candidates.clear();\n"
        "        self.kakan_candidates.clear();\n"
        "        self.chankan_chance = None;\n\n"
        "        self.at_ippatsu = false;\n",
        "        self.ankan_candidates.clear();\n"
        "        self.kakan_candidates.clear();\n"
        "        self.chankan_chance = None;\n"
        "        self.nukidora_ron_chance = None;\n\n"
        "        self.at_ippatsu = false;\n",
        "reset nukidora ron chance",
    )
    text = replace_once(
        text,
        "        self.can_w_riichi = true;\n"
        "        self.is_w_riichi = false;\n"
        "        self.chis.clear();\n",
        "        self.can_w_riichi = true;\n"
        "        self.is_w_riichi = false;\n"
        "        self.nukidora_seen = false;\n"
        "        self.chis.clear();\n",
        "reset nukidora seen",
    )
    text = replace_once(
        text,
        "        // haitei tile cannot be used for kakan or ankan\n"
        "        if self.tiles_left == 0 {\n"
        "            return Ok(());\n"
        "        }\n\n"
        "        if self.riichi_accepted[0] {\n",
        "        // haitei tile cannot be used for kakan, ankan or nukidora.\n"
        "        if self.tiles_left == 0 {\n"
        "            return Ok(());\n"
        "        }\n"
        "        self.update_nukidora_candidate();\n\n"
        "        if self.riichi_accepted[0] {\n",
        "nukidora candidate after tsumo",
    )
    text = replace_once(
        text,
        "        self.last_cans.can_riichi = self.is_menzen\n"
        "            && self.tiles_left >= self.num_players\n"
        "            && self.scores[0] >= 1000\n"
        "            && (self.shanten == 0 || self.shanten == 1 && self.has_next_shanten_discard);\n\n"
        "        Ok(())\n"
        "    }\n\n"
        "    fn dahai(&mut self, actor: u8, pai: Tile, tsumogiri: bool) -> Result<()> {\n",
        "        self.last_cans.can_riichi = self.is_menzen\n"
        "            && self.tiles_left >= self.num_players\n"
        "            && self.scores[0] >= 1000\n"
        "            && (self.shanten == 0 || self.shanten == 1 && self.has_next_shanten_discard);\n\n"
        "        Ok(())\n"
        "    }\n\n"
        "    fn update_nukidora_candidate(&mut self) {\n"
        "        if self.num_players == 3 && self.tiles_left > 0 && self.tehai[tuz!(N)] > 0 {\n"
        "            self.last_cans.can_nukidora = true;\n"
        "        }\n"
        "    }\n\n"
        "    fn nukidora(&mut self, actor: u8, pai: Tile) -> Result<()> {\n"
        "        ensure!(pai == must_tile!(tu8!(N)), \"nukidora tile must be N, got {pai}\");\n"
        "        let actor_rel = self.rel(actor);\n"
        "        self.nukidora_seen = true;\n\n"
        "        if actor_rel != 0 {\n"
        "            self.witness_tile(pai)?;\n"
        "            self.last_kawa_tile = Some(pai);\n"
        "            self.can_w_riichi = false;\n"
        "            self.doras_owned[actor_rel] = self.doras_owned[actor_rel].saturating_add(1);\n"
        "            self.doras_seen = self.doras_seen.saturating_add(1);\n\n"
        "            if !self.at_furiten && self.waits[pai.deaka().as_usize()] {\n"
        "                if self.riichi_accepted[0] || self.tiles_left == 0 {\n"
        "                    self.last_cans.can_ron_agari = true;\n"
        "                } else {\n"
        "                    let mut tehai_with_winning_tile = self.tehai;\n"
        "                    tehai_with_winning_tile[pai.deaka().as_usize()] += 1;\n"
        "                    let agari_calc = AgariCalculator {\n"
        "                        tehai: &tehai_with_winning_tile,\n"
        "                        is_menzen: self.is_menzen,\n"
        "                        chis: &self.chis,\n"
        "                        pons: &self.pons,\n"
        "                        minkans: &self.minkans,\n"
        "                        ankans: &self.ankans,\n"
        "                        bakaze: self.bakaze.as_u8(),\n"
        "                        jikaze: self.jikaze.as_u8(),\n"
        "                        winning_tile: pai.deaka().as_u8(),\n"
        "                        is_ron: true,\n"
        "                    };\n"
        "                    self.last_cans.can_ron_agari = agari_calc.has_yaku();\n"
        "                }\n"
        "            }\n"
        "            if self.last_cans.can_ron_agari {\n"
        "                self.to_mark_same_cycle_furiten = Some(());\n"
        "                self.nukidora_ron_chance = Some(());\n"
        "            } else {\n"
        "                self.at_ippatsu = false;\n"
        "            }\n"
        "            return Ok(());\n"
        "        }\n\n"
        "        self.move_tile(pai, MoveType::Discard)?;\n"
        "        self.doras_owned[0] = self.doras_owned[0].saturating_add(1);\n"
        "        self.doras_seen = self.doras_seen.saturating_add(1);\n"
        "        self.at_ippatsu = false;\n"
        "        self.at_rinshan = true;\n"
        "        self.can_w_riichi = false;\n"
        "        self.update_shanten();\n"
        "        self.update_waits_and_furiten();\n"
        "        self.last_self_tsumo = None;\n"
        "        self.last_cans.can_discard = false;\n"
        "        self.last_cans.can_nukidora = false;\n"
        "        Ok(())\n"
        "    }\n\n"
        "    fn dahai(&mut self, actor: u8, pai: Tile, tsumogiri: bool) -> Result<()> {\n",
        "nukidora state implementation",
    )
    text = replace_once(
        text,
        "        self.update_shanten();\n"
        "        self.update_shanten_discards();\n\n"
        "        Ok(())\n"
        "    }\n\n"
        "    fn daiminkan(&mut self, actor: u8, target: u8, pai: Tile, consumed: [Tile; 3]) -> Result<()> {\n",
        "        self.update_shanten();\n"
        "        self.update_shanten_discards();\n"
        "        self.update_nukidora_candidate();\n\n"
        "        Ok(())\n"
        "    }\n\n"
        "    fn daiminkan(&mut self, actor: u8, target: u8, pai: Tile, consumed: [Tile; 3]) -> Result<()> {\n",
        "nukidora candidate after pon",
    )
    text = replace_once(
        text,
        "        if actor_rel == 0 {\n"
        "            self.at_ippatsu = true;\n"
        "        }\n"
        "    }\n",
        "        if actor_rel == 0 {\n"
        "            self.at_ippatsu = self.num_players == 4 || !self.nukidora_seen;\n"
        "        }\n"
        "    }\n",
        "nukidora ippatsu blocker",
    )
    return text


def patch_file(root: Path, rel: str, transform) -> None:
    path = root / rel
    if not path.is_file():
        raise RuntimeError(f"missing file: {path}")
    original = path.read_text(encoding="utf-8")
    updated = transform(original)
    if updated != original:
        backup = path.with_suffix(path.suffix + ".unified-stage3d.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(updated, encoding="utf-8")
        print(f"patched: {path}")
    else:
        print(f"unchanged: {path}")


def apply(root: Path) -> None:
    patch_file(root, "libriichi/src/state/player_state.rs", patch_player_state)
    patch_file(root, "libriichi/src/state/update.rs", patch_update)

    checks = {
        "libriichi/src/state/player_state.rs": "nukidora_ron_chance",
        "libriichi/src/state/update.rs": "fn update_nukidora_candidate",
    }
    for rel, needle in checks.items():
        text = (root / rel).read_text(encoding="utf-8")
        if MARKER not in text or needle not in text:
            raise RuntimeError(f"Stage 3D postcondition failed: {rel}: {needle}")
    if "nukidora state transition is not installed yet" in (root / "libriichi/src/state/update.rs").read_text(encoding="utf-8"):
        raise RuntimeError("old Stage 3C nukidora transition gate still present")
    print("MORTAL_UNIFIED_NUKIDORA_STAGE3D_OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    apply(args.root.expanduser().resolve())


if __name__ == "__main__":
    main()
