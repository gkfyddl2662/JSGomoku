from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from patch_libriichi_unified_stage3e import (
    AGENT_REQUIRES,
    MARKER,
    OBS_SHA,
    STATE_REQUIRES,
    git_blob_sha,
    patch_consts,
    patch_obs,
    replace_once,
)


def patch_agent(text: str) -> str:
    if MARKER in text:
        return text
    if AGENT_REQUIRES not in text:
        raise RuntimeError("Stage 3E requires unified agent Stage 2")

    text = "// " + MARKER + "\n" + text
    text = replace_once(
        text,
        "use crate::{must_tile, tu8};\n",
        "use crate::{must_tile, t, tu8};\n",
        "agent t macro",
    )

    old_gate = (
        "        ensure!(\n"
        "            self.game_mode == \"4p\",\n"
        "            \"3P action translation is not installed yet; unified libriichi Stage 3 is required\"\n"
        "        );\n\n"
        "        let orig_action = self.actions[action_idx];\n"
    )
    new_gate = "        let orig_action = self.actions[action_idx];\n"
    gate_count = text.count(old_gate)
    if gate_count != 1:
        raise RuntimeError(f"remove 3P translator safety gate: expected one anchor, found {gate_count}")
    text = text.replace(old_gate, new_gate, 1)

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
        "            // 45\n"
        "            _ => Event::None,\n"
        "        };\n\n"
        "        let mut meta = self.gen_meta(state, action_idx);\n",
        "            // 45\n"
        "            _ => Event::None,\n"
        "            }\n"
        "        };\n\n"
        "        let mut meta = self.gen_meta(state, action_idx);\n",
        "close translated action match",
    )
    return text


def patch_file(
    root: Path,
    rel: str,
    transform,
    *,
    expected_sha: str | None = None,
    required: str | None = None,
) -> None:
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
    if not update.is_file() or STATE_REQUIRES not in update.read_text(encoding="utf-8"):
        raise RuntimeError("Stage 3E requires Stage 3D")

    patch_file(root, "libriichi/src/consts.rs", patch_consts)
    patch_file(root, "libriichi/src/state/obs_repr.rs", patch_obs, expected_sha=OBS_SHA)
    patch_file(root, "libriichi/src/agent/mortal.rs", patch_agent, required=AGENT_REQUIRES)

    checks = {
        "libriichi/src/consts.rs": (
            "ACTION_NUKIDORA_3P",
            "obs_shape_for_players",
        ),
        "libriichi/src/state/obs_repr.rs": (
            "obs_shape_for_players",
            "ACTION_NUKIDORA_3P",
            "ACTION_SPACE_3P",
        ),
        "libriichi/src/agent/mortal.rs": (
            "translated_action",
            "Event::Nukidora",
            "agari_action",
        ),
    }
    for rel, needles in checks.items():
        text = (root / rel).read_text(encoding="utf-8")
        if MARKER not in text:
            raise RuntimeError(f"Stage 3E marker missing: {rel}")
        missing = [needle for needle in needles if needle not in text]
        if missing:
            raise RuntimeError(f"Stage 3E postcondition failed: {rel}: {missing}")

    agent = (root / "libriichi/src/agent/mortal.rs").read_text(encoding="utf-8")
    if "3P action translation is not installed yet" in agent:
        raise RuntimeError("old 3P action translation safety gate still present")

    print("MORTAL_UNIFIED_ACTION_OBS_STAGE3E_OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    apply(args.root.expanduser().resolve())


if __name__ == "__main__":
    main()
