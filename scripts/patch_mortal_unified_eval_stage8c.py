from __future__ import annotations

import argparse
import py_compile
import subprocess
from pathlib import Path


MARKER = "# MORTAL_ROGS_UNIFIED_EVAL_STAGE8C"
STAGE8A_MARKER = "# MORTAL_ROGS_UNIFIED_PYTHON_ABI_STAGE8A"
UPSTREAM_SHA = "23ecb3bd5710f6092e71b6215fe1ab9f4cbb8c86"


def git_blob_sha(path: Path) -> str:
    return subprocess.run(
        ["git", "hash-object", str(path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


ONE_VS_THREE = r'''import prelude

import os
import numpy as np
import secrets
import torch
from model import Brain, DQN
from engine import MortalEngine
from libriichi.arena import OneVsThree
from config import config

# MORTAL_ROGS_UNIFIED_EVAL_STAGE8C
MODE = '4p'
PLAYERS = 4
ACTION_SPACE = 46
OBS_CHANNELS = 1012


def _build_engine(state_file, side_cfg, default_name):
    state = torch.load(state_file, weights_only=True, map_location=torch.device('cpu'))
    state_cfg = state['config']
    version = int(state_cfg['control'].get('version', 1))
    if version != 4:
        raise ValueError(f'unified 4P evaluator requires Mortal v4, got v{version}')
    game_cfg = state_cfg.get('game', {})
    checkpoint_mode = str(game_cfg.get('mode', MODE)).lower()
    if checkpoint_mode not in ('4', '4p', 'yonma'):
        raise ValueError(f'4P evaluator received non-4P checkpoint mode {checkpoint_mode!r}')
    action_space = int(game_cfg.get('action_space', ACTION_SPACE))
    obs_channels = int(game_cfg.get('obs_channels', OBS_CHANNELS))
    if action_space != ACTION_SPACE:
        raise ValueError(f'4P checkpoint action space {action_space} != {ACTION_SPACE}')
    if obs_channels != OBS_CHANNELS:
        raise ValueError(f'4P checkpoint obs channels {obs_channels} != {OBS_CHANNELS}')

    conv_channels = int(state_cfg['resnet']['conv_channels'])
    num_blocks = int(state_cfg['resnet']['num_blocks'])
    mortal = Brain(
        version=version,
        conv_channels=conv_channels,
        num_blocks=num_blocks,
        obs_channels=obs_channels,
    ).eval()
    dqn = DQN(version=version, action_space=action_space).eval()
    mortal.load_state_dict(state['mortal'], strict=True)
    dqn.load_state_dict(state['current_dqn'], strict=True)

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
    cfg = config.get('1v3')
    if not isinstance(cfg, dict):
        raise KeyError('expected [1v3] config')

    games_per_iter = int(cfg.get('games_per_iter', 100))
    if games_per_iter <= 0 or games_per_iter % PLAYERS != 0:
        raise ValueError('1v3.games_per_iter must be a positive multiple of 4')
    seeds_per_iter = games_per_iter // PLAYERS
    iters = int(cfg.get('iters', 10))
    log_dir = cfg.get('log_dir')
    use_akochan = bool(cfg.get('akochan', {}).get('enabled', False))
    rank_pts = np.asarray(cfg.get('rank_pts', [90, 45, 0, -135]), dtype=np.float64)
    if rank_pts.shape != (PLAYERS,):
        raise ValueError(f'1v3.rank_pts must contain {PLAYERS} values')

    challenger_cfg = dict(cfg.get('challenger', {}))
    challenger_state = challenger_cfg.get('state_file')
    if not challenger_state:
        raise ValueError('1v3 challenger.state_file must be configured')
    engine_chal = _build_engine(challenger_state, challenger_cfg, 'challenger-4p')

    if use_akochan:
        ako_cfg = dict(cfg.get('akochan', {}))
        ako_dir = ako_cfg.get('dir')
        ako_tactics = ako_cfg.get('tactics')
        if not ako_dir or not ako_tactics:
            raise ValueError('1v3 Akochan mode requires akochan.dir and tactics')
        os.environ['AKOCHAN_DIR'] = str(ako_dir)
        os.environ['AKOCHAN_TACTICS'] = str(ako_tactics)
        engine_cham = None
    else:
        champion_cfg = dict(cfg.get('champion', {}))
        champion_state = champion_cfg.get('state_file')
        if not champion_state:
            raise ValueError('1v3 champion.state_file must be configured when Akochan is disabled')
        engine_cham = _build_engine(champion_state, champion_cfg, 'champion-4p')

    key = int(cfg.get('seed_key', -1))
    if key == -1:
        key = secrets.randbits(64)

    seed_start = int(cfg.get('seed_start', 10000))
    for i, seed in enumerate(range(seed_start, seed_start + seeds_per_iter * iters, seeds_per_iter)):
        print('-' * 50)
        print('#', i)
        env = OneVsThree(disable_progress_bar=False, log_dir=log_dir)
        if use_akochan:
            rankings = env.ako_vs_py(
                engine=engine_chal,
                seed_start=(seed, key),
                seed_count=seeds_per_iter,
            )
        else:
            rankings = env.py_vs_py(
                challenger=engine_chal,
                champion=engine_cham,
                seed_start=(seed, key),
                seed_count=seeds_per_iter,
            )
        rankings = np.asarray(rankings, dtype=np.int64)
        if rankings.shape != (PLAYERS,) or rankings.sum() <= 0:
            raise RuntimeError(f'invalid 4P rankings returned: {rankings}')
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
    target = mortal / "one_vs_three.py"
    if not target.is_file():
        raise RuntimeError(f"missing stock 4P evaluator: {target}")

    existing = target.read_text(encoding="utf-8")
    if MARKER not in existing:
        actual = git_blob_sha(target)
        if actual != UPSTREAM_SHA and STAGE8A_MARKER not in existing:
            raise RuntimeError(
                f"refusing to overwrite unexpected 4P evaluator: expected upstream {UPSTREAM_SHA} "
                f"or managed Stage 8A file, got {actual}"
            )
        target.write_text(ONE_VS_THREE, encoding="utf-8")
        print(f"patched: {target}")
    elif existing != ONE_VS_THREE:
        target.write_text(ONE_VS_THREE, encoding="utf-8")
        print(f"updated: {target}")
    else:
        print(f"unchanged: {target}")

    py_compile.compile(str(target), doraise=True)
    post = target.read_text(encoding="utf-8")
    for token in (
        MARKER,
        "ACTION_SPACE = 46",
        "OBS_CHANNELS = 1012",
        "OneVsThree",
        "game_mode=MODE",
        "action_space=ACTION_SPACE",
        "strict=True",
    ):
        if token not in post:
            raise RuntimeError(f"Stage 8C postcondition missing: {token}")
    print("MORTAL_UNIFIED_EVAL_STAGE8C_OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    apply(args.root)


if __name__ == "__main__":
    main()
