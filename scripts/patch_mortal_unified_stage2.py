from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


TRAIN_SHA = "17bd7eb9096631a0acbdcec8fe9925c1d8477026"
DATALOADER_SHA = "17b79ef3f6cd836e4c7b1e2da442f6ef28e083fe"
REWARD_SHA = "c44772c48551a866c53cd58bddb7330bfa900d02"
MARKER = "# MORTAL_ROGS_UNIFIED_TRAINER_STAGE2"
DATALOADER_MARKER = "# MORTAL_ROGS_UNIFIED_DATALOADER_STAGE2"
REWARD_MARKER = "# MORTAL_ROGS_UNIFIED_REWARD_STAGE2"


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


def patch_dataloader(text: str) -> str:
    if DATALOADER_MARKER in text:
        return text
    text = replace_once(
        text,
        "from config import config\n",
        f"from config import config\n\n{DATALOADER_MARKER}\n",
        "dataloader marker",
    )
    text = replace_once(
        text,
        "        self.grp = GRP(**config['grp']['network'])\n"
        "        grp_state = torch.load(config['grp']['state_file'], weights_only=True, map_location=torch.device('cpu'))\n"
        "        self.grp.load_state_dict(grp_state['model'])\n"
        "        self.reward_calc = RewardCalculator(self.grp, self.pts)\n",
        "        game_cfg = config.get('game', {})\n"
        "        game_mode = str(game_cfg.get('mode', config.get('control', {}).get('game_mode', '4p'))).casefold()\n"
        "        if game_mode in ('3', '3p', 'sanma'):\n"
        "            game_mode = '3p'\n"
        "            num_players, grp_input_size = 3, int(game_cfg.get('grp_input_size', 6))\n"
        "        elif game_mode in ('4', '4p', 'yonma'):\n"
        "            game_mode = '4p'\n"
        "            num_players, grp_input_size = 4, int(game_cfg.get('grp_input_size', 7))\n"
        "        else:\n"
        "            raise ValueError(f'Unsupported game mode: {game_mode!r}')\n"
        "        self.num_players = num_players\n"
        "        network_cfg = dict(config['grp']['network'])\n"
        "        network_cfg['num_players'] = num_players\n"
        "        network_cfg['input_size'] = grp_input_size\n"
        "        self.grp = GRP(**network_cfg)\n"
        "        grp_state = torch.load(config['grp']['state_file'], weights_only=True, map_location=torch.device('cpu'))\n"
        "        self.grp.load_state_dict(grp_state['model'])\n"
        "        global_reward = config.get('global_reward', {})\n"
        "        self.global_reward_enabled = bool(global_reward.get('enabled', False))\n"
        "        self.score_delta_weight = float(global_reward.get('score_delta_weight', 0.0))\n"
        "        self.score_scale = float(global_reward.get('score_scale', 12000.0))\n"
        "        if self.global_reward_enabled and self.score_scale <= 0:\n"
        "            raise ValueError('global_reward.score_scale must be positive')\n"
        "        reward_pts = self.pts\n"
        "        if self.global_reward_enabled:\n"
        "            reward_pts = list(global_reward.get(\n"
        "                f'rank_utility_{game_mode}',\n"
        "                global_reward.get('rank_utility', self.pts[:num_players]),\n"
        "            ))\n"
        "            if len(reward_pts) != num_players:\n"
        "                raise ValueError(\n"
        "                    f'global_reward rank utility for {game_mode} must have {num_players} entries, got {len(reward_pts)}'\n"
        "                )\n"
        "        self.reward_calc = RewardCalculator(self.grp, reward_pts, num_players=num_players)\n",
        "mode-aware gameplay reward construction",
    )
    text = replace_once(
        text,
        "                final_scores = grp.take_final_scores()\n"
        "                scores_seq = np.concatenate((grp_feature[:, 3:] * 1e4, [final_scores]))\n",
        "                final_scores = np.asarray(grp.take_final_scores())[:self.num_players]\n"
        "                if self.global_reward_enabled and self.score_delta_weight != 0:\n"
        "                    score_rewards = self.reward_calc.calc_delta_points(player_id, grp_feature, final_scores)\n"
        "                    if len(score_rewards) != len(kyoku_rewards):\n"
        "                        raise RuntimeError('rank and score reward sequences disagree')\n"
        "                    kyoku_rewards = kyoku_rewards + score_rewards / self.score_scale * self.score_delta_weight\n"
        "                scores_seq = np.concatenate((grp_feature[:, 3:] * 1e4, [final_scores]))\n",
        "mode-aware final score and global reward shaping",
    )
    return text


def patch_reward_calculator(text: str) -> str:
    if REWARD_MARKER in text:
        return text
    text = replace_once(
        text,
        "import numpy as np\n\nclass RewardCalculator:\n",
        f"import numpy as np\n\n{REWARD_MARKER}\n\nclass RewardCalculator:\n",
        "reward marker",
    )
    text = replace_once(
        text,
        "    def __init__(self, grp=None, pts=None, uniform_init=False):\n"
        "        self.device = torch.device('cpu')\n"
        "        self.grp = grp.to(self.device).eval()\n"
        "        self.uniform_init = uniform_init\n\n"
        "        pts = pts or [3, 1, -1, -3]\n"
        "        self.pts = torch.tensor(pts, dtype=torch.float64, device=self.device)\n",
        "    def __init__(self, grp=None, pts=None, uniform_init=False, num_players=4):\n"
        "        self.device = torch.device('cpu')\n"
        "        self.grp = grp.to(self.device).eval()\n"
        "        self.uniform_init = uniform_init\n"
        "        self.num_players = int(num_players)\n"
        "        if self.num_players not in (3, 4):\n"
        "            raise ValueError(f'num_players must be 3 or 4, got {self.num_players}')\n\n"
        "        pts = list(pts or [3, 1, -1, -3])\n"
        "        if len(pts) < self.num_players:\n"
        "            raise ValueError(f'pts must contain at least {self.num_players} entries, got {len(pts)}')\n"
        "        self.pts = torch.tensor(pts[:self.num_players], dtype=torch.float64, device=self.device)\n",
        "mode-aware reward constructor",
    )
    text = replace_once(
        text,
        "        final_ranking = torch.zeros((1, 4), device=self.device)\n"
        "        final_ranking[0, rank_by_player[player_id]] = 1.\n"
        "        rank_prob = torch.cat((matrix[:, player_id], final_ranking))\n"
        "        if self.uniform_init:\n"
        "            rank_prob[0, :] = 1 / 4\n",
        "        final_ranking = torch.zeros((1, self.num_players), device=self.device)\n"
        "        final_ranking[0, rank_by_player[player_id]] = 1.\n"
        "        rank_prob = torch.cat((matrix[:, player_id], final_ranking))\n"
        "        if self.uniform_init:\n"
        "            rank_prob[0, :] = 1 / self.num_players\n",
        "mode-aware final ranking",
    )
    return text


def patch_guarded(path: Path, marker: str, expected_sha: str, transform, backup_suffix: str) -> None:
    original = path.read_text(encoding="utf-8")
    if marker not in original:
        actual = git_blob_sha(path)
        if actual != expected_sha:
            raise RuntimeError(f"unexpected stock Mortal {path.name}: expected {expected_sha}, got {actual}")
    updated = transform(original)
    if updated == original:
        print(f"unchanged: {path}")
        return
    backup = path.with_suffix(backup_suffix)
    if not backup.exists():
        shutil.copy2(path, backup)
    path.write_text(updated, encoding="utf-8")
    print(f"patched: {path}")


def apply(root: Path) -> None:
    mortal = root / "mortal"
    train = mortal / "train.py"
    model = mortal / "model.py"
    dataloader = mortal / "dataloader.py"
    reward = mortal / "reward_calculator.py"
    for path in (train, model, dataloader, reward):
        if not path.is_file():
            raise RuntimeError(f"stock Mortal file not found: {path}")
    if "# MORTAL_ROGS_UNIFIED_MODEL_STAGE1" not in model.read_text(encoding="utf-8"):
        raise RuntimeError("apply unified model Stage 1 before trainer Stage 2")

    patch_guarded(train, MARKER, TRAIN_SHA, patch_train, ".py.unified-stage2.bak")
    patch_guarded(dataloader, DATALOADER_MARKER, DATALOADER_SHA, patch_dataloader, ".py.unified-stage2.bak")
    patch_guarded(reward, REWARD_MARKER, REWARD_SHA, patch_reward_calculator, ".py.unified-stage2.bak")

    train_text = train.read_text(encoding="utf-8")
    dataloader_text = dataloader.read_text(encoding="utf-8")
    reward_text = reward.read_text(encoding="utf-8")
    required_train = (
        MARKER,
        "game_mode = '3p'",
        "game_mode = '4p'",
        "oracle_obs_channels', 170",
        "DQN(version=version, action_space=action_space)",
        "AuxNet((num_players,))",
        "masks.shape[-1] == action_space",
    )
    required_dataloader = (
        DATALOADER_MARKER,
        "self.num_players = num_players",
        "network_cfg['num_players'] = num_players",
        "network_cfg['input_size'] = grp_input_size",
        "self.global_reward_enabled",
        "rank_utility_{game_mode}",
        "RewardCalculator(self.grp, reward_pts, num_players=num_players)",
        "np.asarray(grp.take_final_scores())[:self.num_players]",
        "calc_delta_points(player_id, grp_feature, final_scores)",
        "score_rewards / self.score_scale * self.score_delta_weight",
    )
    required_reward = (
        REWARD_MARKER,
        "self.num_players = int(num_players)",
        "pts[:self.num_players]",
        "torch.zeros((1, self.num_players)",
        "1 / self.num_players",
    )
    missing = [needle for needle in required_train if needle not in train_text]
    missing += [needle for needle in required_dataloader if needle not in dataloader_text]
    missing += [needle for needle in required_reward if needle not in reward_text]
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
