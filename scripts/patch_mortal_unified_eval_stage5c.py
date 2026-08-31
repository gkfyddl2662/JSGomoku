from __future__ import annotations

import argparse
import py_compile
from pathlib import Path


MARKER = "# MORTAL_ROGS_UNIFIED_EVAL_STAGE5C"
LEGACY_MARKER = "# MORTAL_ROGS_AKAGI_LEGACY_3P_BRIDGE_V1"

AKAGI_LEGACY_3P = r'''from __future__ import annotations

import json
import sys
from pathlib import Path

# MORTAL_ROGS_AKAGI_LEGACY_3P_BRIDGE_V1
LEGACY_OBS_CHANNELS = 775
ACTION_SPACE = 44


def _load_libriichi3p():
    runtime_root = Path(__file__).resolve().parents[1]
    compat_lib = runtime_root / 'compat' / 'akagi-ng' / 'lib'
    if not compat_lib.is_dir():
        raise RuntimeError(
            f'Akagi 3P compatibility library is missing: {compat_lib}; '
            'rerun RUN_SELFPLAY_POPULATION.bat prepare 3p ...'
        )
    value = str(compat_lib)
    if value not in sys.path:
        sys.path.insert(0, value)
    import libriichi3p

    shape = tuple(libriichi3p.consts.obs_shape(4))
    if shape != (LEGACY_OBS_CHANNELS, 34):
        raise RuntimeError(f'pinned libriichi3p v4 obs shape mismatch: {shape}')
    if int(libriichi3p.consts.ACTION_SPACE) != ACTION_SPACE:
        raise RuntimeError(f'pinned libriichi3p action space mismatch: {libriichi3p.consts.ACTION_SPACE}')
    return libriichi3p


class AkagiLegacy3PMjaiLogEngine:
    engine_type = 'mjai-log'

    def __init__(self, provider, name: str):
        self.provider = provider
        self.name = name
        self.player_ids = None
        self._lib = _load_libriichi3p()
        self._bots = {}
        self._consumed = {}

    def set_player_ids(self, player_ids):
        self.player_ids = [int(value) for value in player_ids]

    def _new_bot(self, game_idx: int):
        if self.player_ids is None:
            raise RuntimeError('Akagi legacy 3P bridge did not receive player ids')
        player_id = self.player_ids[game_idx]
        bot = self._lib.mjai.Bot(self.provider, player_id)
        bot.react('{"type":"start_game"}')
        self._bots[game_idx] = bot
        self._consumed[game_idx] = 0
        return bot

    def start_game(self, game_idx: int):
        self._new_bot(int(game_idx))

    def react_batch(self, game_states):
        outputs = []
        for game_state in game_states:
            game_idx = int(game_state.game_index)
            bot = self._bots.get(game_idx) or self._new_bot(game_idx)
            events = json.loads(game_state.events_json)
            if not isinstance(events, list) or not events:
                raise RuntimeError(f'Akagi legacy 3P received empty mjai log for game {game_idx}')

            consumed = int(self._consumed.get(game_idx, 0))
            if consumed > len(events):
                # MjaiLogBatchAgent starts a fresh per-kyoku log after end_kyoku.
                consumed = 0
            response = None
            for event in events[consumed:]:
                event_json = json.dumps(event, ensure_ascii=False, separators=(',', ':'))
                current = bot.react(event_json)
                if current:
                    response = current
            self._consumed[game_idx] = len(events)
            if not response:
                raise RuntimeError(
                    f'Akagi legacy 3P bot produced no action for game {game_idx}; '
                    f'events={len(events)} consumed_before={consumed}'
                )
            outputs.append(response)
        return outputs

    def end_kyoku(self, game_idx: int):
        game_idx = int(game_idx)
        bot = self._bots.get(game_idx)
        if bot is not None:
            bot.react('{"type":"end_kyoku"}')
        self._consumed[game_idx] = 0

    def end_game(self, game_idx: int, scores):
        game_idx = int(game_idx)
        bot = self._bots.pop(game_idx, None)
        if bot is not None:
            bot.react('{"type":"end_game"}')
        self._consumed.pop(game_idx, None)
'''

ONE_VS_TWO = r'''import prelude

import numpy as np
import secrets
import torch
from model import Brain, DQN
from engine import MortalEngine
from libriichi.arena import OneVsTwo
from config import config
from akagi_legacy_3p import AkagiLegacy3PMjaiLogEngine

# MORTAL_ROGS_UNIFIED_EVAL_STAGE5C
MODE = '3p'
PLAYERS = 3
ACTION_SPACE = 44
NATIVE_OBS_CHANNELS = 1010
AKAGI_LEGACY_OBS_CHANNELS = 775


def _checkpoint_obs_channels(state):
    try:
        weight = state['mortal']['encoder.net.0.weight']
    except (KeyError, TypeError) as exc:
        raise ValueError('3P checkpoint is missing mortal.encoder.net.0.weight') from exc
    if getattr(weight, 'ndim', None) != 3:
        raise ValueError(f'unexpected encoder.net.0.weight shape: {getattr(weight, "shape", None)}')
    return int(weight.shape[1])


def _build_provider(state, state_cfg, side_cfg, default_name, obs_channels):
    version = int(state_cfg['control'].get('version', 1))
    conv_channels = int(state_cfg['resnet']['conv_channels'])
    num_blocks = int(state_cfg['resnet']['num_blocks'])
    mortal = Brain(
        version=version,
        conv_channels=conv_channels,
        num_blocks=num_blocks,
        obs_channels=obs_channels,
    ).eval()
    dqn = DQN(version=version, action_space=ACTION_SPACE).eval()
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


def _build_engine(state_file, side_cfg, default_name):
    state = torch.load(state_file, weights_only=True, map_location=torch.device('cpu'))
    state_cfg = state['config']
    version = int(state_cfg['control'].get('version', 1))
    if version != 4:
        raise ValueError(f'unified 3P evaluator requires Mortal v4, got v{version}')
    game_cfg = state_cfg.get('game', {})
    action_space = int(game_cfg.get('action_space', ACTION_SPACE))
    if action_space != ACTION_SPACE:
        raise ValueError(f'3P checkpoint action space {action_space} != {ACTION_SPACE}')

    obs_channels = _checkpoint_obs_channels(state)
    if obs_channels == NATIVE_OBS_CHANNELS:
        configured = game_cfg.get('obs_channels')
        if configured is not None and int(configured) != NATIVE_OBS_CHANNELS:
            raise ValueError(
                f'3P native checkpoint config obs channels {configured} != {NATIVE_OBS_CHANNELS}'
            )
        return _build_provider(state, state_cfg, side_cfg, default_name, obs_channels)

    if obs_channels == AKAGI_LEGACY_OBS_CHANNELS:
        provider = _build_provider(state, state_cfg, side_cfg, default_name, obs_channels)
        return AkagiLegacy3PMjaiLogEngine(provider, str(side_cfg.get('name', default_name)))

    raise ValueError(
        f'unsupported 3P checkpoint observation ABI: {obs_channels}; '
        f'expected {NATIVE_OBS_CHANNELS} native or {AKAGI_LEGACY_OBS_CHANNELS} Akagi legacy'
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


def _write_managed(target: Path, content: str, marker: str) -> None:
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        if marker not in existing:
            raise RuntimeError(f"refusing to overwrite unexpected generated file: {target}")
        if existing == content:
            print(f"unchanged: {target}")
            return
        target.write_text(content, encoding="utf-8")
        print(f"updated: {target}")
        return
    target.write_text(content, encoding="utf-8")
    print(f"created: {target}")


def apply(root: Path) -> None:
    root = root.expanduser().resolve()
    mortal = root / "mortal"
    if not mortal.is_dir():
        raise RuntimeError(f"missing Mortal Python directory: {mortal}")

    target = mortal / "one_vs_two.py"
    bridge = mortal / "akagi_legacy_3p.py"
    _write_managed(target, ONE_VS_TWO, MARKER)
    _write_managed(bridge, AKAGI_LEGACY_3P, LEGACY_MARKER)

    py_compile.compile(str(target), doraise=True)
    py_compile.compile(str(bridge), doraise=True)
    post = target.read_text(encoding="utf-8")
    bridge_post = bridge.read_text(encoding="utf-8")
    for token in (
        MARKER,
        "ACTION_SPACE = 44",
        "NATIVE_OBS_CHANNELS = 1010",
        "AKAGI_LEGACY_OBS_CHANNELS = 775",
        "AkagiLegacy3PMjaiLogEngine",
        "OneVsTwo",
        "game_mode=MODE",
        "action_space=ACTION_SPACE",
    ):
        if token not in post:
            raise RuntimeError(f"Stage 5C postcondition missing: {token}")
    for token in (LEGACY_MARKER, "engine_type = 'mjai-log'", "libriichi3p", "LEGACY_OBS_CHANNELS = 775"):
        if token not in bridge_post:
            raise RuntimeError(f"Stage 5C legacy bridge postcondition missing: {token}")
    print("MORTAL_UNIFIED_EVAL_STAGE5C_OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    apply(args.root)


if __name__ == "__main__":
    main()
