from __future__ import annotations

import argparse
import py_compile
import shutil
import subprocess
from pathlib import Path


MARKER = "# MORTAL_ROGS_UNIFIED_ONLINE_STAGE7B"
PLAYER_SHA = "07eee57c809ae67caa7bcd1722e3e2ce2a2a4847"
CLIENT_SHA = "fc6a97d0d3db7cbde163228780bccb6c3b263567"
TRAIN_REQUIRES = "# MORTAL_ROGS_UNIFIED_TRAINER_STAGE2"
STAT_REQUIRES = "MORTAL_ROGS_UNIFIED_STAT_STAGE7A"

PLAYER = r'''import torch
import numpy as np
import os
import shutil
import secrets
import logging
from os import path
from model import Brain, DQN
from engine import MortalEngine
from libriichi.stat import Stat
from libriichi.arena import OneVsThree, OneVsTwo
from config import config

# MORTAL_ROGS_UNIFIED_ONLINE_STAGE7B

def _contract():
    game = config.get('game', {})
    mode = str(game.get('mode', config['control'].get('game_mode', '4p'))).casefold()
    if mode in ('3', '3p', 'sanma'):
        return '3p', 3, 44, 1010, OneVsTwo
    if mode in ('4', '4p', 'yonma'):
        return '4p', 4, 46, 1012, OneVsThree
    raise ValueError(f'unsupported game mode: {mode!r}')

MODE, NUM_PLAYERS, ACTION_SPACE, OBS_CHANNELS, ARENA = _contract()


def _build_engine(state_file, side_cfg, *, default_name, rule_guard):
    device = torch.device(side_cfg.get('device', 'cuda:0'))
    state = torch.load(state_file, weights_only=True, map_location=torch.device('cpu'))
    cfg = state['config']
    version = int(cfg['control'].get('version', 1))
    if version != 4:
        raise ValueError(f'unified {MODE} runtime requires Mortal v4, got v{version}')
    state_game = cfg.get('game', {})
    action_space = int(state_game.get('action_space', ACTION_SPACE))
    obs_channels = int(state_game.get('obs_channels', OBS_CHANNELS))
    if action_space != ACTION_SPACE:
        raise ValueError(f'{MODE} checkpoint action space {action_space} != {ACTION_SPACE}')
    if obs_channels != OBS_CHANNELS:
        raise ValueError(f'{MODE} checkpoint obs channels {obs_channels} != {OBS_CHANNELS}')

    mortal = Brain(
        version=version,
        conv_channels=int(cfg['resnet']['conv_channels']),
        num_blocks=int(cfg['resnet']['num_blocks']),
        obs_channels=obs_channels,
    ).eval()
    dqn = DQN(version=version, action_space=action_space).eval()
    mortal.load_state_dict(state['mortal'])
    dqn.load_state_dict(state['current_dqn'])
    if bool(side_cfg.get('enable_compile', False)):
        mortal.compile()
        dqn.compile()

    engine = MortalEngine(
        mortal,
        dqn,
        is_oracle=False,
        version=version,
        device=device,
        enable_amp=bool(side_cfg.get('enable_amp', True)),
        enable_rule_based_agari_guard=bool(side_cfg.get('enable_rule_based_agari_guard', rule_guard)),
        name=str(side_cfg.get('name', default_name)),
        game_mode=MODE,
        action_space=ACTION_SPACE,
    )
    return engine


class TestPlayer:
    def __init__(self):
        baseline_cfg = config['baseline']['test']
        self.baseline_engine = _build_engine(
            baseline_cfg['state_file'],
            baseline_cfg,
            default_name='baseline',
            rule_guard=True,
        )
        self.chal_version = int(config['control']['version'])
        if self.chal_version != 4:
            raise ValueError(f'unified runtime requires v4, got v{self.chal_version}')
        self.log_dir = path.abspath(config['test_play']['log_dir'])

    def test_play(self, seed_count, mortal, dqn, device):
        torch.backends.cudnn.benchmark = False
        engine_chal = MortalEngine(
            mortal,
            dqn,
            is_oracle=False,
            version=self.chal_version,
            device=device,
            enable_amp=True,
            name='mortal',
            game_mode=MODE,
            action_space=ACTION_SPACE,
        )

        if path.isdir(self.log_dir):
            shutil.rmtree(self.log_dir)
        env = ARENA(disable_progress_bar=False, log_dir=self.log_dir)
        env.py_vs_py(
            challenger=engine_chal,
            champion=self.baseline_engine,
            seed_start=(10000, 0x2000),
            seed_count=seed_count,
        )
        stat = Stat.from_dir(self.log_dir, 'mortal')
        torch.backends.cudnn.benchmark = config['control']['enable_cudnn_benchmark']
        return stat


class TrainPlayer:
    def __init__(self):
        baseline_cfg = config['baseline']['train']
        self.baseline_engine = _build_engine(
            baseline_cfg['state_file'],
            baseline_cfg,
            default_name='baseline',
            rule_guard=True,
        )

        profile = os.environ.get('TRAIN_PLAY_PROFILE', 'default')
        logging.info(f'using profile {profile} in {MODE}')
        cfg = config['train_play'][profile]
        self.chal_version = int(config['control']['version'])
        if self.chal_version != 4:
            raise ValueError(f'unified runtime requires v4, got v{self.chal_version}')
        self.log_dir = path.abspath(cfg['log_dir'])
        self.train_key = secrets.randbits(64)
        self.train_seed = 10000

        games = int(cfg['games'])
        if games <= 0 or games % NUM_PLAYERS != 0:
            raise ValueError(f'train_play.games must be a positive multiple of {NUM_PLAYERS}, got {games}')
        self.seed_count = games // NUM_PLAYERS
        self.boltzmann_epsilon = cfg['boltzmann_epsilon']
        self.boltzmann_temp = cfg['boltzmann_temp']
        self.top_p = cfg['top_p']
        self.repeats = cfg['repeats']
        self.repeat_counter = 0

    def train_play(self, mortal, dqn, device):
        torch.backends.cudnn.benchmark = False
        engine_chal = MortalEngine(
            mortal,
            dqn,
            is_oracle=False,
            version=self.chal_version,
            boltzmann_epsilon=self.boltzmann_epsilon,
            boltzmann_temp=self.boltzmann_temp,
            top_p=self.top_p,
            device=device,
            enable_amp=True,
            name='trainee',
            game_mode=MODE,
            action_space=ACTION_SPACE,
        )

        if path.isdir(self.log_dir):
            shutil.rmtree(self.log_dir)
        env = ARENA(disable_progress_bar=False, log_dir=self.log_dir)
        rankings = env.py_vs_py(
            challenger=engine_chal,
            champion=self.baseline_engine,
            seed_start=(self.train_seed, self.train_key),
            seed_count=self.seed_count,
        )
        self.repeat_counter += 1
        if self.repeat_counter == self.repeats:
            self.train_seed += self.seed_count
            self.repeat_counter = 0

        rankings = np.asarray(rankings)
        if rankings.shape != (NUM_PLAYERS,):
            raise RuntimeError(f'{MODE} arena returned invalid rankings shape {rankings.shape}')
        file_list = [path.join(self.log_dir, p) for p in os.listdir(self.log_dir)]
        torch.backends.cudnn.benchmark = config['control']['enable_cudnn_benchmark']
        return rankings, file_list
'''

CLIENT = r'''import prelude

import gc
import logging
import socket
import time
from os import path

import numpy as np
import torch
from model import Brain, DQN
from player import TrainPlayer, MODE, NUM_PLAYERS, ACTION_SPACE, OBS_CHANNELS
from common import send_msg, recv_msg
from config import config

# MORTAL_ROGS_UNIFIED_ONLINE_STAGE7B

def main():
    remote = (config['online']['remote']['host'], config['online']['remote']['port'])
    device = torch.device(config['control']['device'])
    version = int(config['control']['version'])
    if version != 4:
        raise ValueError(f'unified {MODE} client requires Mortal v4, got v{version}')

    mortal = Brain(
        version=version,
        num_blocks=int(config['resnet']['num_blocks']),
        conv_channels=int(config['resnet']['conv_channels']),
        obs_channels=OBS_CHANNELS,
    ).to(device).eval()
    dqn = DQN(version=version, action_space=ACTION_SPACE).to(device)
    if config['online']['enable_compile']:
        mortal.compile()
        dqn.compile()

    train_player = TrainPlayer()
    param_version = -1
    if MODE == '3p':
        pts = np.asarray(config['online'].get('rank_pts', [6, 0, -6]))
    else:
        pts = np.asarray(config['online'].get('rank_pts', [90, 45, 0, -135]))
    if pts.shape != (NUM_PLAYERS,):
        raise ValueError(f'{MODE} online.rank_pts must have {NUM_PLAYERS} entries')

    history_window = int(config['online']['history_window'])
    history = []

    while True:
        while True:
            with socket.socket() as conn:
                conn.connect(remote)
                send_msg(conn, {'type': 'get_param', 'param_version': param_version})
                rsp = recv_msg(conn, map_location=device)
                if rsp['status'] == 'ok':
                    param_version = rsp['param_version']
                    break
                time.sleep(3)
        mortal.load_state_dict(rsp['mortal'])
        dqn.load_state_dict(rsp['dqn'])
        logging.info(f'{MODE} param has been updated')

        rankings, file_list = train_player.train_play(mortal, dqn, device)
        avg_rank = rankings @ np.arange(1, NUM_PLAYERS + 1) / rankings.sum()
        avg_pt = rankings @ pts / rankings.sum()

        history.append(np.asarray(rankings))
        if len(history) > history_window:
            del history[0]
        sum_rankings = np.sum(history, axis=0)
        ma_avg_rank = sum_rankings @ np.arange(1, NUM_PLAYERS + 1) / sum_rankings.sum()
        ma_avg_pt = sum_rankings @ pts / sum_rankings.sum()

        logging.info(f'{MODE} trainee rankings: {rankings} ({avg_rank:.6}, {avg_pt:.6}pt)')
        logging.info(f'last {len(history)} sessions: {sum_rankings} ({ma_avg_rank:.6}, {ma_avg_pt:.6}pt)')

        logs = {}
        for filename in file_list:
            with open(filename, 'rb') as f:
                logs[path.basename(filename)] = f.read()

        with socket.socket() as conn:
            conn.connect(remote)
            send_msg(conn, {
                'type': 'submit_replay',
                'logs': logs,
                'param_version': param_version,
            })
            logging.info(f'{MODE} logs have been submitted')
        gc.collect()
        if device.type == 'cuda':
            torch.cuda.empty_cache()
            torch.cuda.synchronize(device)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
'''


def git_blob_sha(path: Path) -> str:
    return subprocess.run(
        ["git", "hash-object", str(path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def write_pinned(path: Path, expected_sha: str, content: str) -> None:
    original = path.read_text(encoding="utf-8")
    if MARKER not in original:
        actual = git_blob_sha(path)
        if actual != expected_sha:
            raise RuntimeError(f"unexpected canonical {path.name}: expected {expected_sha}, got {actual}")
    if original != content:
        backup = path.with_suffix(path.suffix + ".unified-stage7b.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(content, encoding="utf-8")
        print(f"patched: {path}")
    else:
        print(f"unchanged: {path}")


def patch_train(text: str) -> str:
    if MARKER in text:
        return text
    if TRAIN_REQUIRES not in text:
        raise RuntimeError("Stage 7B requires unified trainer Stage 2")
    text = text.replace(
        "    test_games = config['test_play']['games']\n",
        "    test_games = config['test_play']['games']\n"
        "    test_rank_pts = (\n"
        "        list(config.get('1v2', {}).get('rank_pts', [6, 0, -6]))\n"
        "        if num_players == 3\n"
        "        else [90, 45, 0, -135]\n"
        "    )\n"
        "    if len(test_rank_pts) != num_players:\n"
        "        raise ValueError(f'{game_mode} test rank points must have {num_players} entries')\n",
        1,
    )
    text = text.replace(
        "                    stat = test_player.test_play(test_games // 4, mortal, dqn, device)\n",
        "                    if test_games % num_players != 0:\n"
        "                        raise ValueError(f'test_play.games must be divisible by {num_players}')\n"
        "                    stat = test_player.test_play(test_games // num_players, mortal, dqn, device)\n",
        1,
    )
    text = text.replace(
        "                    avg_pt = stat.avg_pt([90, 45, 0, -135]) # for display only, never used in training\n",
        "                    avg_pt = stat.avg_pt(test_rank_pts) # display/promotion metric only\n",
        1,
    )
    marker_anchor = "    game_cfg = config.get('game', {})\n"
    if marker_anchor not in text:
        raise RuntimeError("Stage 7B trainer game-mode anchor missing")
    return text.replace(marker_anchor, f"    {MARKER}\n" + marker_anchor, 1)


def apply(root: Path) -> None:
    root = root.expanduser().resolve()
    mortal = root / "mortal"
    stat = root / "libriichi/src/stat.rs"
    if not stat.is_file() or STAT_REQUIRES not in stat.read_text(encoding="utf-8"):
        raise RuntimeError("Stage 7B requires unified statistics Stage 7A")

    player = mortal / "player.py"
    client = mortal / "client.py"
    train = mortal / "train.py"
    for path in (player, client, train):
        if not path.is_file():
            raise RuntimeError(f"missing Mortal file: {path}")

    write_pinned(player, PLAYER_SHA, PLAYER)
    write_pinned(client, CLIENT_SHA, CLIENT)

    original_train = train.read_text(encoding="utf-8")
    updated_train = patch_train(original_train)
    if updated_train != original_train:
        backup = train.with_suffix(train.suffix + ".unified-stage7b.bak")
        if not backup.exists():
            shutil.copy2(train, backup)
        train.write_text(updated_train, encoding="utf-8")
        print(f"patched: {train}")
    else:
        print(f"unchanged: {train}")

    for path in (player, client, train):
        py_compile.compile(str(path), doraise=True)
    checks = {
        player: (MARKER, "OneVsThree, OneVsTwo", "games // NUM_PLAYERS", "action_space=ACTION_SPACE"),
        client: (MARKER, "np.arange(1, NUM_PLAYERS + 1)", "obs_channels=OBS_CHANNELS"),
        train: (MARKER, "test_games // num_players", "stat.avg_pt(test_rank_pts)"),
    }
    for path, tokens in checks.items():
        post = path.read_text(encoding="utf-8")
        missing = [token for token in tokens if token not in post]
        if missing:
            raise RuntimeError(f"Stage 7B postconditions failed for {path.name}: {missing}")
    print("MORTAL_UNIFIED_ONLINE_STAGE7B_OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    apply(args.root)


if __name__ == "__main__":
    main()
