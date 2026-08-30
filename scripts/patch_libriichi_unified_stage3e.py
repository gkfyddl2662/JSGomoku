from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


MARKER = "MORTAL_ROGS_UNIFIED_ACTION_OBS_STAGE3E"
STATE_REQUIRES = "MORTAL_ROGS_UNIFIED_NUKIDORA_STAGE3D"
AGENT_REQUIRES = "MORTAL_ROGS_UNIFIED_AGENT_STAGE2"
OBS_SHA = "998917f1755424771a51fc9507c5864b54dd6545"


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


def patch_consts(text: str) -> str:
    if MARKER in text:
        return text
    text = "// " + MARKER + "\n" + text
    text = replace_once(
        text,
        "pub const ACTION_SPACE_3P: usize = 44;\n"
        "pub const ACTION_SPACE_4P: usize = 46;\n"
        "pub const ACTION_SPACE: usize = ACTION_SPACE_4P; // legacy 4P API\n",
        "pub const ACTION_SPACE_3P: usize = 44;\n"
        "pub const ACTION_SPACE_4P: usize = 46;\n"
        "pub const ACTION_SPACE: usize = ACTION_SPACE_4P; // legacy 4P API\n\n"
        "pub const ACTION_RIICHI_3P: usize = 37;\n"
        "pub const ACTION_NUKIDORA_3P: usize = 38;\n"
        "pub const ACTION_PON_3P: usize = 39;\n"
        "pub const ACTION_KAN_3P: usize = 40;\n"
        "pub const ACTION_AGARI_3P: usize = 41;\n"
        "pub const ACTION_RYUKYOKU_3P: usize = 42;\n"
        "pub const ACTION_PASS_3P: usize = 43;\n",
        "3P action constants",
    )
    text = replace_once(
        text,
        "#[pyfunction]\n"
        "pub fn obs_shape_for(mode: &str, version: u32) -> PyResult<(usize, usize)> {\n"
        "    match normalize_mode(mode)? {\n"
        "        \"3p\" => match version {\n"
        "            1 => Ok((936, 34)),\n"
        "            2 => Ok((940, 34)),\n"
        "            3 => Ok((932, 34)),\n"
        "            4 => Ok((1010, 34)),\n"
        "            _ => Err(PyValueError::new_err(format!(\n"
        "                \"unsupported 3P Mortal version: {version}\"\n"
        "            ))),\n"
        "        },\n"
        "        \"4p\" => match version {\n"
        "            1..=4 => Ok(obs_shape(version)),\n"
        "            _ => Err(PyValueError::new_err(format!(\n"
        "                \"unsupported 4P Mortal version: {version}\"\n"
        "            ))),\n"
        "        },\n"
        "        _ => unreachable!(),\n"
        "    }\n"
        "}\n",
        "#[inline]\n"
        "pub const fn obs_shape_for_players(num_players: usize, version: u32) -> (usize, usize) {\n"
        "    match (num_players, version) {\n"
        "        (3, 1) => (936, 34),\n"
        "        (3, 2) => (940, 34),\n"
        "        (3, 3) => (932, 34),\n"
        "        (3, 4) => (1010, 34),\n"
        "        (4, 1..=4) => obs_shape(version),\n"
        "        _ => panic!(\"unsupported Mortal player/version combination\"),\n"
        "    }\n"
        "}\n\n"
        "#[pyfunction]\n"
        "pub fn obs_shape_for(mode: &str, version: u32) -> PyResult<(usize, usize)> {\n"
        "    let players = if normalize_mode(mode)? == \"3p\" { 3 } else { 4 };\n"
        "    if !(1..=4).contains(&version) {\n"
        "        return Err(PyValueError::new_err(format!(\"unsupported Mortal version: {version}\")));\n"
        "    }\n"
        "    Ok(obs_shape_for_players(players, version))\n"
        "}\n",
        "pure obs shape helper",
    )
    return text


def patch_obs(text: str) -> str:
    if MARKER in text:
        return text
    text = "// " + MARKER + "\n" + text
    text = replace_once(
        text,
        "use crate::consts::{ACTION_SPACE, MAX_VERSION, obs_shape};\n",
        "use crate::consts::{\n"
        "    ACTION_AGARI_3P, ACTION_KAN_3P, ACTION_NUKIDORA_3P, ACTION_PASS_3P, ACTION_PON_3P,\n"
        "    ACTION_RIICHI_3P, ACTION_RYUKYOKU_3P, ACTION_SPACE_3P, ACTION_SPACE_4P, MAX_VERSION,\n"
        "    obs_shape_for_players,\n"
        "};\n",
        "obs dynamic imports",
    )
    text = replace_once(
        text,
        "        let shape = obs_shape(version);\n"
        "        let arr = Simple2DArray::new(shape.0);\n"
        "        let mask = Array1::default(ACTION_SPACE);\n",
        "        let num_players = state.num_players as usize;\n"
        "        let shape = obs_shape_for_players(num_players, version);\n"
        "        let arr = Simple2DArray::new(shape.0);\n"
        "        let action_space = if num_players == 3 { ACTION_SPACE_3P } else { ACTION_SPACE_4P };\n"
        "        let mask = Array1::default(action_space);\n",
        "obs shape and mask width",
    )
    text = replace_once(
        text,
        "        let v = state.tiles_left as f32 / 69.;\n",
        "        let tiles_scale = if state.num_players == 3 { 55. } else { 69. };\n"
        "        let v = state.tiles_left as f32 / tiles_scale;\n",
        "mode-aware live wall feature",
    )
    text = replace_once(
        text,
        "                self.mask[ACTION_SPACE - 1] = true;\n",
        "                let pass = if state.num_players == 3 { ACTION_PASS_3P } else { ACTION_SPACE_4P - 1 };\n"
        "                self.mask[pass] = true;\n",
        "mode-aware pass mask",
    )
    old_actions = '''        if cans.can_riichi {
            self.arr.fill(self.idx, 1.);
            if !self.at_kan_select {
                self.mask[37] = true;
            }
        }
        self.idx += 1;

        if cans.can_chi_low {
            self.arr.fill(self.idx, 1.);
            if !self.at_kan_select {
                self.mask[38] = true;
            }
        }
        if cans.can_chi_mid {
            self.arr.fill(self.idx + 1, 1.);
            if !self.at_kan_select {
                self.mask[39] = true;
            }
        }
        if cans.can_chi_high {
            self.arr.fill(self.idx + 2, 1.);
            if !self.at_kan_select {
                self.mask[40] = true;
            }
        }
        self.idx += 3;

        if cans.can_pon {
            self.arr.fill(self.idx, 1.);
            if !self.at_kan_select {
                self.mask[41] = true;
            }
        }
        self.idx += 1;

        if cans.can_daiminkan {
            self.arr.fill(self.idx, 1.);
            if !self.at_kan_select {
                self.mask[42] = true;
            }
        }
        self.idx += 1;

        if cans.can_ankan {
            for tile in state.ankan_candidates {
                self.arr.assign(self.idx, tile.as_usize(), 1.);
                if self.at_kan_select {
                    self.mask[tile.as_usize()] = true;
                }
            }
            if !self.at_kan_select {
                self.mask[42] = true;
            }
        }
        self.idx += 1;

        if cans.can_kakan {
            for tile in state.kakan_candidates {
                self.arr.assign(self.idx, tile.as_usize(), 1.);
                if self.at_kan_select {
                    self.mask[tile.as_usize()] = true;
                }
            }
            if !self.at_kan_select {
                self.mask[42] = true;
            }
        }
        self.idx += 1;

        if cans.can_agari() {
            self.arr.fill(self.idx, 1.);
            if !self.at_kan_select {
                self.mask[43] = true;
            }
        }
        self.idx += 1;

        if cans.can_ryukyoku {
            self.arr.fill(self.idx, 1.);
            if !self.at_kan_select {
                self.mask[44] = true;
            }
        }
        self.idx += 1;
'''
    new_actions = '''        if cans.can_riichi {
            self.arr.fill(self.idx, 1.);
            if !self.at_kan_select {
                self.mask[37] = true;
            }
        }
        self.idx += 1;

        if state.num_players == 3 {
            if cans.can_nukidora {
                self.arr.assign(self.idx, tuz!(N), 1.);
                if !self.at_kan_select {
                    self.mask[ACTION_NUKIDORA_3P] = true;
                }
            }
            self.idx += 1;
        } else {
            if cans.can_chi_low {
                self.arr.fill(self.idx, 1.);
                if !self.at_kan_select {
                    self.mask[38] = true;
                }
            }
            if cans.can_chi_mid {
                self.arr.fill(self.idx + 1, 1.);
                if !self.at_kan_select {
                    self.mask[39] = true;
                }
            }
            if cans.can_chi_high {
                self.arr.fill(self.idx + 2, 1.);
                if !self.at_kan_select {
                    self.mask[40] = true;
                }
            }
            self.idx += 3;
        }

        let pon_action = if state.num_players == 3 { ACTION_PON_3P } else { 41 };
        let kan_action = if state.num_players == 3 { ACTION_KAN_3P } else { 42 };
        let agari_action = if state.num_players == 3 { ACTION_AGARI_3P } else { 43 };
        let ryukyoku_action = if state.num_players == 3 { ACTION_RYUKYOKU_3P } else { 44 };

        if cans.can_pon {
            self.arr.fill(self.idx, 1.);
            if !self.at_kan_select {
                self.mask[pon_action] = true;
            }
        }
        self.idx += 1;

        if cans.can_daiminkan {
            self.arr.fill(self.idx, 1.);
            if !self.at_kan_select {
                self.mask[kan_action] = true;
            }
        }
        self.idx += 1;

        if cans.can_ankan {
            for tile in state.ankan_candidates {
                self.arr.assign(self.idx, tile.as_usize(), 1.);
                if self.at_kan_select {
                    self.mask[tile.as_usize()] = true;
                }
            }
            if !self.at_kan_select {
                self.mask[kan_action] = true;
            }
        }
        self.idx += 1;

        if cans.can_kakan {
            for tile in state.kakan_candidates {
                self.arr.assign(self.idx, tile.as_usize(), 1.);
                if self.at_kan_select {
                    self.mask[tile.as_usize()] = true;
                }
            }
            if !self.at_kan_select {
                self.mask[kan_action] = true;
            }
        }
        self.idx += 1;

        if cans.can_agari() {
            self.arr.fill(self.idx, 1.);
            if !self.at_kan_select {
                self.mask[agari_action] = true;
            }
        }
        self.idx += 1;

        if cans.can_ryukyoku {
            self.arr.fill(self.idx, 1.);
            if !self.at_kan_select {
                self.mask[ryukyoku_action] = true;
            }
        }
        self.idx += 1;
'''
    text = replace_once(text, old_actions, new_actions, "mode-aware action feature planes")
    return text


def patch_agent(text: str) -> str:
    if MARKER in text:
        return text
    if AGENT_REQUIRES not in text:
        raise RuntimeError("Stage 3E requires unified agent Stage 2")
    text = "// " + MARKER + "\n" + text
    text = replace_once(text, "use crate::{must_tile, tu8};\n", "use crate::{must_tile, t, tu8};\n", "agent t macro")
    text = replace_once(
        text,
        "        ensure!(\n"
        "            self.game_mode == \"4p\",\n"
        "            \"3P action translation is not installed yet; unified libriichi Stage 3 is required\"\n"
        "        );\n\n"
        "        let orig_action = self.actions[action_idx];\n",
        "        let orig_action = self.actions[action_idx];\n",
        "remove 3P translator safety gate",
    )
    text = replace_once(
        text,
        "            && !cans.can_riichi\n"
        "            && !cans.can_tsumo_agari\n",
        "            && !cans.can_riichi\n"
        "            && !cans.can_nukidora\n"
        "            && !cans.can_tsumo_agari\n",
        "quick eval nukidora guard",
    )
    text = replace_once(
        text,
        "        let action =\n"
        "            if self.enable_rule_based_agari_guard && orig_action == 43 && !state.rule_based_agari()\n"
        "            {\n",
        "        let agari_action = if self.game_mode == \"3p\" { 41 } else { 43 };\n"
        "        let action =\n"
        "            if self.enable_rule_based_agari_guard\n"
        "                && orig_action == agari_action\n"
        "                && !state.rule_based_agari()\n"
        "            {\n",
        "mode-aware agari guard",
    )
    text = replace_once(
        text,
        "                q_values[43] = f32::MIN;\n",
        "                q_values[agari_action] = f32::MIN;\n",
        "mode-aware agari q mask",
    )
    text = replace_once(
        text,
        "        let event = match action {\n",
        "        let translated_action = if self.game_mode == \"3p\" {\n"
        "            match action {\n"
        "                39 => 41,\n"
        "                40 => 42,\n"
        "                41 => 43,\n"
        "                42 => 44,\n"
        "                43 => 45,\n"
        "                _ => action,\n"
        "            }\n"
        "        } else {\n"
        "            action\n"
        "        };\n\n"
        "        let event = if self.game_mode == \"3p\" && action == 38 {\n"
        "            ensure!(\n"
        "                cans.can_nukidora,\n"
        "                \"failed nukidora check: {}\",\n"
        "                state.brief_info()\n"
        "            );\n"
        "            Event::Nukidora { actor, pai: t!(N) }\n"
        "        } else {\n"
        "            match translated_action {\n",
        "3P action translation prelude",
    )
    text = replace_once(
        text,
        "            _ => anyhow::bail!(\"invalid action index {action}\"),\n"
        "        };\n\n"
        "        let mut meta = self.gen_meta(state, action_idx);\n",
        "            _ => anyhow::bail!(\"invalid action index {action}\"),\n"
        "            }\n"
        "        };\n\n"
        "        let mut meta = self.gen_meta(state, action_idx);\n",
        "close translated action match",
    )
    return text


def patch_file(root: Path, rel: str, transform, expected_sha: str | None = None, required: str | None = None) -> None:
    path = root / rel
    if not path.is_file():
        raise RuntimeError(f"missing file: {path}")
    original = path.read_text(encoding="utf-8")
    if required and required not in original:
        raise RuntimeError(f"{rel} missing prerequisite marker {required}")
    if expected_sha and MARKER not in original:
        actual = git_blob_sha(path)
        if actual != expected_sha:
            raise RuntimeError(f"unexpected upstream {rel}: expected {expected_sha}, got {actual}")
    updated = transform(original)
    if updated != original:
        backup = path.with_suffix(path.suffix + ".unified-stage3e.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(updated, encoding="utf-8")
        print(f"patched: {path}")
    else:
        print(f"unchanged: {path}")


def apply(root: Path) -> None:
    update = root / "libriichi/src/state/update.rs"
    if STATE_REQUIRES not in update.read_text(encoding="utf-8"):
        raise RuntimeError("Stage 3E requires Stage 3D")

    patch_file(root, "libriichi/src/consts.rs", patch_consts)
    patch_file(root, "libriichi/src/state/obs_repr.rs", patch_obs, expected_sha=OBS_SHA)
    patch_file(root, "libriichi/src/agent/mortal.rs", patch_agent, required=AGENT_REQUIRES)

    checks = {
        "libriichi/src/consts.rs": "ACTION_NUKIDORA_3P",
        "libriichi/src/state/obs_repr.rs": "obs_shape_for_players",
        "libriichi/src/agent/mortal.rs": "translated_action",
    }
    for rel, needle in checks.items():
        text = (root / rel).read_text(encoding="utf-8")
        if MARKER not in text or needle not in text:
            raise RuntimeError(f"Stage 3E postcondition failed: {rel}: {needle}")
    if "3P action translation is not installed yet" in (root / "libriichi/src/agent/mortal.rs").read_text(encoding="utf-8"):
        raise RuntimeError("old 3P action translation safety gate still present")
    print("MORTAL_UNIFIED_ACTION_OBS_STAGE3E_OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    apply(args.root.expanduser().resolve())


if __name__ == "__main__":
    main()
