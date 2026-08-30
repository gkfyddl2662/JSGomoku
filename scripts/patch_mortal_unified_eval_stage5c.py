from __future__ import annotations

import argparse
import py_compile
from pathlib import Path


MARKER = "# MORTAL_ROGS_UNIFIED_EVAL_STAGE5C"

ONE_VS_TWO = r'''import prelude

import numpy as np
import secrets
import torch
from model import Brain, DQN
from engine import MortalEngine
from libriichi.arena import OneVsTwo
from config import config

# MORTAL_ROGS_UNIFIED_EVAL_STAGE5C
MODE = '3p'
PLAYERS = 3
ACTION_SPACE = 44
OBS_CHANNELS = 1010


def _build_engine(state_file, side_cfg, default_name):
    state = torch.load(state_file, weights_only=True, map_location=torch.device('cpu'))
    state_cfg = state['config']
    version = int(state_cfg['control'].get('version', 1))
    if version != 4:
        raise ValueError(f'unified 3P evaluator requires Mortal v4, got v{version}')
    game_cfg = state_cfg.get('game', {})
    action_space = int(game_cfg.get('action_space', ACTION_SPACE))
    obs_channels = int(game_cfg.get('obs_channels', OBS_CHANNELS))
    if action_space != ACTION_SPACE:
        raise ValueError(f'3P checkpoint action space {action_space} != {ACTION_SPACE}')
    if obs_channels != OBS_CHANNELS:
        raise ValueError(f'3P checkpoint obs channels {obs_channels} != {OBS_CHANNELS}')

    conv_channels = int(state_cfg['resnet']['conv_channels'])
    num_blocks = int(state_cfg['resnet']['num_blocks'])
    mortal = Brain(
        version=version,
        conv_channels=conv_channels,
        num_blocks=num_blocks,
        obs_channels=obs_channels,
    ).eval()
    dqn = DQN(version=version, action_space=action_space).eval()
    mortal.load_state_dict(state['mortal'])
    dqn.load_state_dict(state['current_dqn'])

    if bool(side_cfg.get('enable_compile', False)):
        mortal.compile()
        dqn.compile()

    return MortalEngine(
        mortal,
        dqn,
        is_oracle=False,
        version=version,
        device=torch.device(side_cfg.get('device', 'cuda:0')),
        enable_amp=bool(side_cfg.get('enable_amp', True)),
        enable_rule_based_agari_guard=bool(side_cfg.get('enable_rule_based_agari_guard', False)),
        name=str(side_cfg.get('name', default_name)),
        game_mode=MODE,
        action_space=ACTION_SPACE,
    )


def main():
    cfg = config.get('1v2')
    if not isinstance(cfg, dict):
        raise KeyError('expected [1v2] config')

    games_per_iter = int(cfg.get('games_per_iter', 96))
    if games_per_iter <= 0 or games_per_iter % PLAYERS != 0:
        raise ValueError('1v2.games_per_iter must be a positive multiple of 3')
    seeds_per_iter = games_per_iter // PLAYERS
    iters = int(cfg.get('iters', 10))
    log_dir = cfg.get('log_dir')
    rank_pts = np.asarray(cfg.get('rank_pts', [6, 0, -6]), dtype=np.float64)
    if rank_pts.shape != (PLAYERS,):
        raise ValueError(f'1v2.rank_pts must contain {PLAYERS} values')

    challenger_cfg = dict(cfg.get('challenger', {}))
    champion_cfg = dict(cfg.get('champion', {}))
    challenger_state = challenger_cfg.get('state_file')
    champion_state = champion_cfg.get('state_file')
    if not challenger_state or not champion_state:
        raise ValueError('1v2 challenger/champion state_file must both be configured')

    engine_chal = _build_engine(challenger_state, challenger_cfg, 'challenger-3p')
    engine_cham = _build_engine(champion_state, champion_cfg, 'champion-3p')

    key = int(cfg.get('seed_key', -1))
    if key == -1:
        key = secrets.randbits(64)

    seed_start = int(cfg.get('seed_start', 10000))
    for i, seed in enumerate(range(seed_start, seed_start + seeds_per_iter * iters, seeds_per_iter)):
        print('-' * 50)
        print('#', i)
        env = OneVsTwo(disable_progress_bar=False, log_dir=log_dir)
        rankings = env.py_vs_py(
            challenger=engine_chal,
            champion=engine_cham,
            seed_start=(seed, key),
            seed_count=seeds_per_iter,
        )
        rankings = np.asarray(rankings, dtype=np.int64)
        if rankings.shape != (PLAYERS,) or rankings.sum() <= 0:
            raise RuntimeError(f'invalid 3P rankings returned: {rankings}')
        avg_rank = rankings @ np.arange(1, PLAYERS + 1) / rankings.sum()
        avg_pt = rankings @ rank_pts / rankings.sum()
        print(f'challenger rankings: {rankings} ({avg_rank}, {avg_pt}pt)')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
'''


def apply(root: Path) -> None:
    root = root.expanduser().resolve()
    mortal = root / "mortal"
    if not mortal.is_dir():
        raise RuntimeError(f"missing Mortal Python directory: {mortal}")
    target = mortal / "one_vs_two.py"
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        if MARKER not in existing:
            raise RuntimeError(f"refusing to overwrite unexpected evaluator: {target}")
        if existing != ONE_VS_TWO:
            target.write_text(ONE_VS_TWO, encoding="utf-8")
            print(f"updated: {target}")
        else:
            print(f"unchanged: {target}")
    else:
        target.write_text(ONE_VS_TWO, encoding="utf-8")
        print(f"created: {target}")

    py_compile.compile(str(target), doraise=True)
    post = target.read_text(encoding="utf-8")
    for token in (
        MARKER,
        "ACTION_SPACE = 44",
        "OBS_CHANNELS = 1010",
        "OneVsTwo",
        "game_mode=MODE",
        "action_space=ACTION_SPACE",
    ):
        if token not in post:
            raise RuntimeError(f"Stage 5C postcondition missing: {token}")
    print("MORTAL_UNIFIED_EVAL_STAGE5C_OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    apply(args.root)


if __name__ == "__main__":
    main()
