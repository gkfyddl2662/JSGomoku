from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


TRAIN_SHA = "17bd7eb9096631a0acbdcec8fe9925c1d8477026"
MARKER = "# MORTAL_ROGS_UNIFIED_TRAINER_STAGE2"


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


def patch_train(text: str) -> str:
    if MARKER in text:
        return text

    text = replace_once(
        text,
        "    version = config['control']['version']\n",
        "    version = config['control']['version']\n"
        f"    {MARKER}\n"
        "    game_cfg = config.get('game', {})\n"
        "    game_mode = str(game_cfg.get('mode', config['control'].get('game_mode', '4p'))).casefold()\n"
        "    if game_mode in ('3', '3p', 'sanma'):\n"
        "        game_mode = '3p'\n"
        "        num_players = 3\n"
        "        action_space = int(game_cfg.get('action_space', 44))\n"
        "        if version != 4:\n"
        "            raise ValueError('Unified 3P deployment currently requires Mortal v4')\n"
        "        obs_channels = int(game_cfg.get('obs_channels', 1010))\n"
        "        oracle_obs_channels = int(game_cfg.get('oracle_obs_channels', 170))\n"
        "        grp_input_size = int(game_cfg.get('grp_input_size', 6))\n"
        "    elif game_mode in ('4', '4p', 'yonma'):\n"
        "        game_mode = '4p'\n"
        "        num_players = 4\n"
        "        action_space = int(game_cfg.get('action_space', 46))\n"
        "        obs_channels = int(game_cfg.get('obs_channels', obs_shape(version)[0]))\n"
        "        oracle_obs_channels = int(game_cfg.get('oracle_obs_channels', 217))\n"
        "        grp_input_size = int(game_cfg.get('grp_input_size', 7))\n"
        "    else:\n"
        "        raise ValueError(f'Unsupported game mode: {game_mode!r}')\n",
        "game mode setup",
    )

    text = replace_once(
        text,
        "    mortal = Brain(version=version, **config['resnet']).to(device)\n"
        "    dqn = DQN(version=version).to(device)\n"
        "    aux_net = AuxNet((4,)).to(device)\n",
        "    mortal = Brain(\n"
        "        version=version,\n"
        "        obs_channels=obs_channels,\n"
        "        oracle_obs_channels=oracle_obs_channels,\n"
        "        **config['resnet'],\n"
        "    ).to(device)\n"
        "    dqn = DQN(version=version, action_space=action_space).to(device)\n"
        "    aux_net = AuxNet((num_players,)).to(device)\n",
        "mode-aware model construction",
    )

    text = replace_once(
        text,
        "    logging.info(f'version: {version}')\n"
        "    logging.info(f'obs shape: {obs_shape(version)}')\n",
        "    logging.info(f'game mode: {game_mode} ({num_players} players)')\n"
        "    logging.info(f'version: {version}')\n"
        "    logging.info(f'obs shape: {(obs_channels, 34)}')\n"
        "    logging.info(f'action space: {action_space}')\n",
        "mode logging",
    )

    text = replace_once(
        text,
        "    best_perf = {\n"
        "        'avg_rank': 4.,\n"
        "        'avg_pt': -135.,\n"
        "    }\n",
        "    best_perf = {\n"
        "        'avg_rank': float(num_players),\n"
        "        'avg_pt': -135.,\n"
        "    }\n",
        "mode-aware initial best performance",
    )

    text = replace_once(
        text,
        "            player_ranks = player_ranks.to(dtype=torch.int64, device=device)\n"
        "            assert masks[range(batch_size), actions].all()\n",
        "            player_ranks = player_ranks.to(dtype=torch.int64, device=device)\n"
        "            assert masks.shape[-1] == action_space, (masks.shape, action_space, game_mode)\n"
        "            assert masks[range(batch_size), actions].all()\n",
        "action-space batch guard",
    )
    return text


def apply(root: Path) -> None:
    train = root / "mortal" / "train.py"
    model = root / "mortal" / "model.py"
    if not train.is_file() or not model.is_file():
        raise RuntimeError(f"stock Mortal trainer/model not found under {root / 'mortal'}")
    if "# MORTAL_ROGS_UNIFIED_MODEL_STAGE1" not in model.read_text(encoding="utf-8"):
        raise RuntimeError("apply unified model Stage 1 before trainer Stage 2")

    original = train.read_text(encoding="utf-8")
    if MARKER not in original:
        actual = git_blob_sha(train)
        if actual != TRAIN_SHA:
            raise RuntimeError(
                f"unexpected stock Mortal train.py: expected {TRAIN_SHA}, got {actual}"
            )

    updated = patch_train(original)
    if updated != original:
        backup = train.with_suffix(".py.unified-stage2.bak")
        if not backup.exists():
            shutil.copy2(train, backup)
        train.write_text(updated, encoding="utf-8")
        print(f"patched: {train}")
    else:
        print(f"unchanged: {train}")

    post = train.read_text(encoding="utf-8")
    required = (
        MARKER,
        "game_mode = '3p'",
        "game_mode = '4p'",
        "oracle_obs_channels', 170",
        "DQN(version=version, action_space=action_space)",
        "AuxNet((num_players,))",
        "masks.shape[-1] == action_space",
    )
    missing = [needle for needle in required if needle not in post]
    if missing:
        raise RuntimeError(f"unified trainer Stage 2 postconditions failed: {missing}")
    print("MORTAL_UNIFIED_TRAINER_STAGE2_OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    apply(args.root.expanduser().resolve())


if __name__ == "__main__":
    main()
