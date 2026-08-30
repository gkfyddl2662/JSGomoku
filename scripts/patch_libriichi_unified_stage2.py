from __future__ import annotations

import argparse
import py_compile
import shutil
import subprocess
from pathlib import Path


ENGINE_SHA = "2196c98cd062f2f1d6e6162f0bdd1b28383d0672"
AGENT_SHA = "e1b14eee8fc489ed07cbc3afbf983d11931f6d69"
ENGINE_MARKER = "# MORTAL_ROGS_UNIFIED_ENGINE_STAGE2"
AGENT_MARKER = "MORTAL_ROGS_UNIFIED_AGENT_STAGE2"


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


def patch_engine(text: str) -> str:
    if ENGINE_MARKER in text:
        return text

    text = replace_once(
        text,
        "class MortalEngine:\n",
        f"{ENGINE_MARKER}\nclass MortalEngine:\n",
        "engine marker",
    )
    text = replace_once(
        text,
        "        top_p = 1,\n    ):\n",
        "        top_p = 1,\n"
        "        game_mode = '4p',\n"
        "        action_space = None,\n"
        "    ):\n",
        "engine mode args",
    )
    text = replace_once(
        text,
        "        self.version = version\n        self.stochastic_latent = stochastic_latent\n",
        "        self.version = version\n"
        "        mode = str(game_mode).lower()\n"
        "        if mode in ('3', '3p', 'sanma'):\n"
        "            mode = '3p'\n"
        "        elif mode in ('4', '4p', 'yonma'):\n"
        "            mode = '4p'\n"
        "        else:\n"
        "            raise ValueError(f'unsupported game mode: {game_mode}')\n"
        "        self.game_mode = mode\n"
        "        inferred_action_space = getattr(dqn, 'action_space', None)\n"
        "        self.action_space = int(action_space if action_space is not None else inferred_action_space or (44 if mode == '3p' else 46))\n"
        "        expected_action_space = 44 if mode == '3p' else 46\n"
        "        if self.action_space != expected_action_space:\n"
        "            raise ValueError(f'{mode} requires {expected_action_space} actions, got {self.action_space}')\n"
        "        self.stochastic_latent = stochastic_latent\n",
        "engine runtime mode",
    )
    text = replace_once(
        text,
        "        masks = torch.as_tensor(np.stack(masks, axis=0), device=self.device)\n",
        "        masks = torch.as_tensor(np.stack(masks, axis=0), device=self.device)\n"
        "        if masks.shape[-1] != self.action_space:\n"
        "            raise ValueError(f'{self.game_mode} mask width {masks.shape[-1]} != action space {self.action_space}')\n",
        "engine mask validation",
    )
    text = replace_once(
        text,
        "                q_out = self.dqn(phi, masks)\n\n        if self.boltzmann_epsilon > 0:\n",
        "                q_out = self.dqn(phi, masks)\n\n"
        "        if q_out.shape[-1] != self.action_space:\n"
        "            raise ValueError(f'{self.game_mode} q width {q_out.shape[-1]} != action space {self.action_space}')\n\n"
        "        if self.boltzmann_epsilon > 0:\n",
        "engine q validation",
    )
    return text


def patch_agent(text: str) -> str:
    if AGENT_MARKER in text:
        return text

    text = replace_once(
        text,
        "use crate::consts::ACTION_SPACE;\n",
        "use crate::consts::{ACTION_SPACE_3P, ACTION_SPACE_4P};\n"
        f"// {AGENT_MARKER}\n",
        "agent imports",
    )
    text = replace_once(
        text,
        "    version: u32,\n    enable_quick_eval: bool,\n",
        "    version: u32,\n"
        "    game_mode: String,\n"
        "    action_space: usize,\n"
        "    enable_quick_eval: bool,\n",
        "agent mode fields",
    )
    text = replace_once(
        text,
        "    q_values: Vec<[f32; ACTION_SPACE]>,\n    masks_recv: Vec<[bool; ACTION_SPACE]>,\n",
        "    q_values: Vec<Vec<f32>>,\n    masks_recv: Vec<Vec<bool>>,\n",
        "agent dynamic vectors",
    )

    old_tuple = '''        let (name, is_oracle, version, enable_quick_eval, enable_rule_based_agari_guard) =
            Python::with_gil(|py| {
'''
    new_tuple = '''        let (name, is_oracle, version, game_mode, action_space, enable_quick_eval, enable_rule_based_agari_guard) =
            Python::with_gil(|py| {
'''
    text = replace_once(text, old_tuple, new_tuple, "agent Python tuple")

    text = replace_once(
        text,
        "                let version = obj.getattr(\"version\")?.extract()?;\n"
        "                let enable_quick_eval = obj.getattr(\"enable_quick_eval\")?.extract()?;\n",
        "                let version = obj.getattr(\"version\")?.extract()?;\n"
        "                let game_mode: String = obj.getattr(\"game_mode\")?.extract()?;\n"
        "                let action_space: usize = obj.getattr(\"action_space\")?.extract()?;\n"
        "                let enable_quick_eval = obj.getattr(\"enable_quick_eval\")?.extract()?;\n",
        "agent Python attrs",
    )
    text = replace_once(
        text,
        "                    version,\n                    enable_quick_eval,\n",
        "                    version,\n                    game_mode,\n                    action_space,\n                    enable_quick_eval,\n",
        "agent tuple values",
    )
    text = replace_once(
        text,
        "            version,\n            enable_quick_eval,\n",
        "            version,\n"
        "            game_mode,\n"
        "            action_space,\n"
        "            enable_quick_eval,\n",
        "agent struct values",
    )

    validation_anchor = "        let size = player_ids.len();\n"
    validation = '''        let expected_action_space = match game_mode.as_str() {
            "3p" => ACTION_SPACE_3P,
            "4p" => ACTION_SPACE_4P,
            _ => anyhow::bail!("unsupported Mortal game_mode {game_mode}"),
        };
        ensure!(
            action_space == expected_action_space,
            "{game_mode} requires {expected_action_space} actions, got {action_space}"
        );

        let size = player_ids.len();
'''
    text = replace_once(text, validation_anchor, validation, "agent action-space validation")

    text = replace_once(
        text,
        "        self.last_eval_elapsed = Instant::now()\n"
        "            .checked_duration_since(start)\n"
        "            .unwrap_or(Duration::ZERO);\n\n"
        "        Ok(())\n",
        "        ensure!(\n"
        "            self.q_values.iter().all(|q| q.len() == self.action_space),\n"
        "            \"Python engine returned an invalid q-vector width for {}\",\n"
        "            self.game_mode\n"
        "        );\n"
        "        ensure!(\n"
        "            self.masks_recv.iter().all(|m| m.len() == self.action_space),\n"
        "            \"Python engine returned an invalid mask width for {}\",\n"
        "            self.game_mode\n"
        "        );\n\n"
        "        self.last_eval_elapsed = Instant::now()\n"
        "            .checked_duration_since(start)\n"
        "            .unwrap_or(Duration::ZERO);\n\n"
        "        Ok(())\n",
        "agent vector validation",
    )

    text = replace_once(
        text,
        "        let q_values = self.q_values[action_idx];\n"
        "        let masks = self.masks_recv[action_idx];\n",
        "        let q_values = &self.q_values[action_idx];\n"
        "        let masks = &self.masks_recv[action_idx];\n",
        "agent metadata refs",
    )
    text = replace_once(
        text,
        "        let q_values_compact = q_values\n            .into_iter()\n            .zip(masks)\n",
        "        let q_values_compact = q_values\n"
        "            .iter()\n"
        "            .copied()\n"
        "            .zip(masks.iter().copied())\n",
        "agent metadata iterators",
    )
    text = replace_once(
        text,
        "                let mut q_values = self.q_values[action_idx];\n",
        "                let mut q_values = self.q_values[action_idx].clone();\n",
        "agent guard vector clone",
    )

    # Stage 2 only changes vector transport. Prevent a 3P engine from silently
    # falling through the still-4P action translator until Stage 3 installs it.
    text = replace_once(
        text,
        "        let orig_action = self.actions[action_idx];\n",
        "        ensure!(\n"
        "            self.game_mode == \"4p\",\n"
        "            \"3P action translation is not installed yet; unified libriichi Stage 3 is required\"\n"
        "        );\n\n"
        "        let orig_action = self.actions[action_idx];\n",
        "agent Stage 3 gate",
    )
    return text


def patch_one(path: Path, expected_sha: str, marker: str, transform, backup_suffix: str) -> None:
    if not path.is_file():
        raise RuntimeError(f"missing upstream file: {path}")
    original = path.read_text(encoding="utf-8")
    if marker not in original:
        actual = git_blob_sha(path)
        if actual != expected_sha:
            raise RuntimeError(f"unexpected upstream {path.name}: expected {expected_sha}, got {actual}")
    updated = transform(original)
    if updated != original:
        backup = path.with_suffix(path.suffix + backup_suffix)
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(updated, encoding="utf-8")
        print(f"patched: {path}")
    else:
        print(f"unchanged: {path}")


def apply(root: Path) -> None:
    engine = root / "mortal" / "engine.py"
    agent = root / "libriichi" / "src" / "agent" / "mortal.rs"
    patch_one(engine, ENGINE_SHA, ENGINE_MARKER, patch_engine, ".unified-stage2.bak")
    patch_one(agent, AGENT_SHA, AGENT_MARKER, patch_agent, ".unified-stage2.bak")

    py_compile.compile(str(engine), doraise=True)
    engine_text = engine.read_text(encoding="utf-8")
    agent_text = agent.read_text(encoding="utf-8")
    required_engine = (ENGINE_MARKER, "self.game_mode = mode", "self.action_space", "q width")
    required_agent = (
        AGENT_MARKER,
        "q_values: Vec<Vec<f32>>",
        "masks_recv: Vec<Vec<bool>>",
        "game_mode: String",
        "action_space: usize",
        "unified libriichi Stage 3 is required",
    )
    missing = [x for x in required_engine if x not in engine_text]
    missing += [x for x in required_agent if x not in agent_text]
    if missing:
        raise RuntimeError(f"unified libriichi Stage 2 postconditions failed: {missing}")
    print("MORTAL_UNIFIED_LIBRIICHI_STAGE2_OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    apply(args.root.expanduser().resolve())


if __name__ == "__main__":
    main()
