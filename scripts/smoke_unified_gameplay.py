from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np


def fail(msg: str) -> None:
    raise RuntimeError(msg)


def main() -> int:
    ap = argparse.ArgumentParser(description="Run real 3P/4P games through one unified Mortal/libriichi runtime.")
    ap.add_argument("--runtime-root", type=Path, required=True)
    ap.add_argument("--device", default="cuda:0")
    args = ap.parse_args()

    root = args.runtime_root.expanduser().resolve()
    mortal_dir = root / "mortal"
    sys.path.insert(0, str(mortal_dir))

    import torch
    import libriichi
    from engine import MortalEngine
    from model import Brain, DQN

    arena = libriichi.arena
    dataset = libriichi.dataset
    device = torch.device(args.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        fail("CUDA gameplay smoke requested but CUDA is unavailable")

    contracts = {
        "3p": {"players": 3, "actions": 44, "obs": 1010, "arena": arena.OneVsTwo},
        "4p": {"players": 4, "actions": 46, "obs": 1012, "arena": arena.OneVsThree},
    }
    result: dict[str, object] = {}
    smoke_root = root / "runtime" / "smoke-gameplay"
    if smoke_root.exists():
        shutil.rmtree(smoke_root)
    smoke_root.mkdir(parents=True, exist_ok=True)

    def make_engine(mode: str, name: str) -> MortalEngine:
        c = contracts[mode]
        brain = Brain(
            version=4,
            conv_channels=16,
            num_blocks=1,
            obs_channels=c["obs"],
        ).to(device).eval()
        dqn = DQN(version=4, action_space=c["actions"]).to(device).eval()
        return MortalEngine(
            brain,
            dqn,
            is_oracle=False,
            version=4,
            device=device,
            enable_amp=(device.type == "cuda"),
            enable_rule_based_agari_guard=True,
            name=name,
            game_mode=mode,
            action_space=c["actions"],
        )

    for idx, (mode, c) in enumerate(contracts.items()):
        log_dir = smoke_root / mode
        log_dir.mkdir(parents=True, exist_ok=True)
        challenger = make_engine(mode, f"smoke-{mode}-challenger")
        champion = make_engine(mode, f"smoke-{mode}-champion")
        env = c["arena"](disable_progress_bar=True, log_dir=str(log_dir))
        rankings = env.py_vs_py(
            challenger=challenger,
            champion=champion,
            seed_start=(12000 + idx * 100, 0x5A17),
            seed_count=1,
        )
        rankings = np.asarray(rankings, dtype=np.int64)
        if rankings.shape != (c["players"],):
            fail(f"{mode} ranking shape {rankings.shape} != {(c['players'],)}")
        if int(rankings.sum()) != c["players"]:
            fail(f"{mode} expected {c['players']} challenger seat-rotation games, got {rankings}")

        logs = sorted(log_dir.glob("*.json.gz"))
        if not logs:
            fail(f"{mode} arena produced no .json.gz logs in {log_dir}")

        loader = dataset.GameplayLoader(
            version=4,
            oracle=False,
            player_names=None,
            excludes=None,
            augmented=False,
        )
        loaded_files = loader.load_gz_log_files([str(p) for p in logs])
        perspectives = 0
        actions_seen = 0
        for loaded_file in loaded_files:
            for game in loaded_file:
                obs = game.take_obs()
                actions = game.take_actions()
                masks = game.take_masks()
                if len(obs) == 0 or len(actions) == 0 or len(masks) == 0:
                    fail(f"{mode} dataset loader returned an empty game perspective")
                obs_arr = np.asarray(obs)
                mask_arr = np.asarray(masks)
                action_arr = np.asarray(actions)
                if obs_arr.shape[1:] != (c["obs"], 34):
                    fail(f"{mode} loaded obs shape {obs_arr.shape}, expected (*,{c['obs']},34)")
                if mask_arr.shape[1:] != (c["actions"],):
                    fail(f"{mode} loaded mask shape {mask_arr.shape}, expected (*,{c['actions']})")
                if action_arr.shape[0] != obs_arr.shape[0] or mask_arr.shape[0] != obs_arr.shape[0]:
                    fail(f"{mode} loaded gameplay lengths disagree")
                if not bool(mask_arr[np.arange(len(action_arr)), action_arr].all()):
                    fail(f"{mode} loaded an action that is illegal under its mask")
                perspectives += 1
                actions_seen += int(len(action_arr))

        if perspectives <= 0 or actions_seen <= 0:
            fail(f"{mode} gameplay loader produced no usable samples")
        result[mode] = {
            "rankings": rankings.tolist(),
            "logs": len(logs),
            "perspectives": perspectives,
            "actions": actions_seen,
            "obs": [c["obs"], 34],
            "action_space": c["actions"],
        }
        del challenger, champion, env, loader, loaded_files
        if device.type == "cuda":
            torch.cuda.empty_cache()
            torch.cuda.synchronize(device)

    print("MORTAL_UNIFIED_GAMEPLAY_E2E_OK")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
