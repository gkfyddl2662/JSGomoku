from __future__ import annotations

import argparse
import py_compile
import shutil
import subprocess
from pathlib import Path


MARKER = "# MORTAL_ROGS_UNIFIED_GRP_TRAINER_STAGE6B"
MODEL_REQUIRES = "# MORTAL_ROGS_UNIFIED_MODEL_STAGE1"
TRAIN_GRP_SHA = "83a114bb38fdf9ec2a81b6bb1e0faa680d246f6a"


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


def patch_train_grp(text: str) -> str:
    if MARKER in text:
        return text
    text = text.replace("import prelude\n", "import prelude\n\n" + MARKER + "\n", 1)

    text = replace_once(
        text,
        "        for game in data:\n"
        "            feature = game.take_feature()\n"
        "            rank_by_player = game.take_rank_by_player()\n\n"
        "            for i in range(feature.shape[0]):\n"
        "                inputs_seq = torch.as_tensor(feature[:i + 1], dtype=torch.float64)\n"
        "                self.buffer.append((\n"
        "                    inputs_seq,\n"
        "                    rank_by_player,\n"
        "                ))\n",
        "        for game in data:\n"
        "            num_players = int(game.get_num_players())\n"
        "            feature = game.take_feature()\n"
        "            rank_by_player = game.take_rank_by_player()[:num_players]\n"
        "            expected_width = 3 + num_players\n"
        "            if feature.shape[1] != expected_width:\n"
        "                raise ValueError(f'GRP feature width {feature.shape[1]} != {expected_width} for {num_players}P')\n\n"
        "            for i in range(feature.shape[0]):\n"
        "                inputs_seq = torch.as_tensor(feature[:i + 1], dtype=torch.float64)\n"
        "                self.buffer.append((\n"
        "                    inputs_seq,\n"
        "                    rank_by_player,\n"
        "                    num_players,\n"
        "                ))\n",
        "mode-aware GRP dataset samples",
    )

    text = replace_once(
        text,
        "def collate(batch):\n"
        "    inputs = []\n"
        "    lengths = []\n"
        "    rank_by_players = []\n"
        "    for inputs_seq, rank_by_player in batch:\n"
        "        inputs.append(inputs_seq)\n"
        "        lengths.append(len(inputs_seq))\n"
        "        rank_by_players.append(rank_by_player)\n\n"
        "    lengths = torch.tensor(lengths)\n"
        "    rank_by_players = torch.tensor(rank_by_players, dtype=torch.int64, pin_memory=True)\n\n"
        "    padded = pad_sequence(inputs, batch_first=True)\n"
        "    packed_inputs = pack_padded_sequence(padded, lengths, batch_first=True, enforce_sorted=False)\n"
        "    packed_inputs.pin_memory()\n\n"
        "    return packed_inputs, rank_by_players\n",
        "def collate(batch):\n"
        "    inputs = []\n"
        "    lengths = []\n"
        "    rank_by_players = []\n"
        "    player_counts = []\n"
        "    for inputs_seq, rank_by_player, num_players in batch:\n"
        "        inputs.append(inputs_seq)\n"
        "        lengths.append(len(inputs_seq))\n"
        "        rank_by_players.append(rank_by_player)\n"
        "        player_counts.append(int(num_players))\n\n"
        "    unique_counts = set(player_counts)\n"
        "    if len(unique_counts) != 1:\n"
        "        raise ValueError(f'mixed 3P/4P GRP samples in one batch: {sorted(unique_counts)}')\n"
        "    num_players = player_counts[0]\n"
        "    lengths = torch.tensor(lengths)\n"
        "    rank_by_players = torch.tensor(rank_by_players, dtype=torch.int64, pin_memory=True)\n\n"
        "    padded = pad_sequence(inputs, batch_first=True)\n"
        "    packed_inputs = pack_padded_sequence(padded, lengths, batch_first=True, enforce_sorted=False)\n"
        "    packed_inputs.pin_memory()\n\n"
        "    return packed_inputs, rank_by_players, num_players\n",
        "mode-aware GRP collate",
    )

    text = replace_once(
        text,
        "def train():\n"
        "    cfg = config['grp']\n"
        "    batch_size = cfg['control']['batch_size']\n",
        "def train():\n"
        "    cfg = config['grp']\n"
        "    game_cfg = config.get('game', {})\n"
        "    game_mode = str(game_cfg.get('mode', config.get('control', {}).get('game_mode', '4p'))).casefold()\n"
        "    if game_mode in ('3', '3p', 'sanma'):\n"
        "        game_mode = '3p'\n"
        "        num_players = 3\n"
        "    elif game_mode in ('4', '4p', 'yonma'):\n"
        "        game_mode = '4p'\n"
        "        num_players = 4\n"
        "    else:\n"
        "        raise ValueError(f'unsupported game mode: {game_mode}')\n"
        "    grp_input_size = 3 + num_players\n"
        "    batch_size = cfg['control']['batch_size']\n",
        "GRP trainer mode setup",
    )

    text = replace_once(
        text,
        "    grp = GRP(**cfg['network']).to(device)\n"
        "    optimizer = optim.AdamW(grp.parameters())\n",
        "    network_cfg = dict(cfg['network'])\n"
        "    network_cfg['num_players'] = num_players\n"
        "    network_cfg['input_size'] = grp_input_size\n"
        "    grp = GRP(**network_cfg).to(device)\n"
        "    optimizer = optim.AdamW(grp.parameters())\n"
        "    logging.info(f'game mode: {game_mode}, GRP input: {grp_input_size}, permutations: {6 if num_players == 3 else 24}')\n",
        "mode-aware GRP model construction",
    )

    text = replace_once(
        text,
        "        grp.load_state_dict(state['model'])\n"
        "        optimizer.load_state_dict(state['optimizer'])\n"
        "        steps = state['steps']\n",
        "        checkpoint_players = int(state.get('num_players', num_players))\n"
        "        if checkpoint_players != num_players:\n"
        "            raise ValueError(f'GRP checkpoint is {checkpoint_players}P, runtime is {num_players}P')\n"
        "        grp.load_state_dict(state['model'])\n"
        "        optimizer.load_state_dict(state['optimizer'])\n"
        "        steps = state['steps']\n",
        "GRP checkpoint mode guard",
    )

    text = text.replace(
        "    for inputs, rank_by_players in train_data_loader:\n"
        "        inputs = inputs.to(dtype=torch.float64, device=device)\n"
        "        rank_by_players = rank_by_players.to(dtype=torch.int64, device=device)\n",
        "    for inputs, rank_by_players, batch_players in train_data_loader:\n"
        "        if batch_players != num_players:\n"
        "            raise ValueError(f'GRP batch is {batch_players}P, trainer is {num_players}P')\n"
        "        inputs = inputs.to(dtype=torch.float64, device=device)\n"
        "        rank_by_players = rank_by_players.to(dtype=torch.int64, device=device)\n",
        1,
    )

    text = text.replace(
        "                for idx, (inputs, rank_by_players) in enumerate(val_data_loader):\n"
        "                    if idx == val_steps:\n"
        "                        break\n"
        "                    inputs = inputs.to(dtype=torch.float64, device=device)\n"
        "                    rank_by_players = rank_by_players.to(dtype=torch.int64, device=device)\n",
        "                for idx, (inputs, rank_by_players, batch_players) in enumerate(val_data_loader):\n"
        "                    if idx == val_steps:\n"
        "                        break\n"
        "                    if batch_players != num_players:\n"
        "                        raise ValueError(f'GRP validation batch is {batch_players}P, trainer is {num_players}P')\n"
        "                    inputs = inputs.to(dtype=torch.float64, device=device)\n"
        "                    rank_by_players = rank_by_players.to(dtype=torch.int64, device=device)\n",
        1,
    )

    text = replace_once(
        text,
        "            state = {\n"
        "                'model': grp.state_dict(),\n"
        "                'optimizer': optimizer.state_dict(),\n"
        "                'steps': steps,\n",
        "            state = {\n"
        "                'model': grp.state_dict(),\n"
        "                'optimizer': optimizer.state_dict(),\n"
        "                'num_players': num_players,\n"
        "                'game_mode': game_mode,\n"
        "                'steps': steps,\n",
        "GRP checkpoint mode metadata",
    )
    return text


def apply(root: Path) -> None:
    model = root / "mortal/model.py"
    if not model.is_file() or MODEL_REQUIRES not in model.read_text(encoding="utf-8"):
        raise RuntimeError("Stage 6B requires unified model Stage 1")

    path = root / "mortal/train_grp.py"
    if not path.is_file():
        raise RuntimeError(f"missing train_grp.py: {path}")
    original = path.read_text(encoding="utf-8")
    if MARKER not in original:
        actual = git_blob_sha(path)
        if actual != TRAIN_GRP_SHA:
            raise RuntimeError(f"unexpected stock train_grp.py: expected {TRAIN_GRP_SHA}, got {actual}")
    updated = patch_train_grp(original)
    if updated != original:
        backup = path.with_suffix(path.suffix + ".unified-stage6b.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(updated, encoding="utf-8")
        print(f"patched: {path}")
    else:
        print(f"unchanged: {path}")

    py_compile.compile(str(path), doraise=True)
    post = path.read_text(encoding="utf-8")
    required = (
        MARKER,
        "game.get_num_players()",
        "mixed 3P/4P GRP samples",
        "network_cfg['num_players'] = num_players",
        "network_cfg['input_size'] = grp_input_size",
        "'num_players': num_players",
    )
    missing = [x for x in required if x not in post]
    if missing:
        raise RuntimeError(f"Stage 6B postconditions failed: {missing}")
    print("MORTAL_UNIFIED_GRP_TRAINER_STAGE6B_OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    apply(args.root.expanduser().resolve())


if __name__ == "__main__":
    main()
