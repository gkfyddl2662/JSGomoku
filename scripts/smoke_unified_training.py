from __future__ import annotations

import argparse
import copy
import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np


def fail(msg: str) -> None:
    raise RuntimeError(msg)


def probe_full_dataloader(
    *,
    mode: str,
    contract: dict[str, int],
    logs: list[Path],
    example_cfg: Path,
    output_root: Path,
    mortal_dir: Path,
    toml,
    torch,
    GRP,
) -> dict[str, object]:
    cfg = copy.deepcopy(toml.load(example_cfg))
    cfg.setdefault("control", {})["version"] = 4
    game = cfg.setdefault("game", {})
    game.update(
        {
            "mode": mode,
            "num_players": contract["players"],
            "action_space": contract["actions"],
            "obs_channels": contract["obs"],
            "grp_input_size": 6 if mode == "3p" else 7,
        }
    )

    grp_state = output_root / f"probe-grp-{mode}.pth"
    cfg_path = output_root / f"probe-config-{mode}.toml"
    cfg.setdefault("grp", {})["state_file"] = str(grp_state)
    network_cfg = dict(cfg["grp"]["network"])
    network_cfg["num_players"] = contract["players"]
    network_cfg["input_size"] = game["grp_input_size"]
    grp = GRP(**network_cfg).cpu().eval()
    torch.save({"model": grp.state_dict()}, grp_state)
    cfg_path.write_text(toml.dumps(cfg), encoding="utf-8")
    del grp

    old_cfg_env = os.environ.get("MORTAL_CFG")
    old_config_module = sys.modules.pop("config", None)
    old_dataloader_module = sys.modules.pop("dataloader", None)
    try:
        os.environ["MORTAL_CFG"] = str(cfg_path)
        importlib.invalidate_caches()
        dataloader = importlib.import_module("dataloader")
        files = [str(path) for path in logs]
        file_data = dataloader.FileDatasetsIter(
            version=4,
            file_list=files,
            pts=cfg["env"]["pts"],
            file_batch_size=max(1, len(files)),
            reserve_ratio=0,
            player_names=None,
            num_epochs=1,
            enable_augmentation=False,
            augmented_first=False,
        )
        sample = next(iter(file_data))
    finally:
        sys.modules.pop("dataloader", None)
        sys.modules.pop("config", None)
        if old_dataloader_module is not None:
            sys.modules["dataloader"] = old_dataloader_module
        if old_config_module is not None:
            sys.modules["config"] = old_config_module
        if old_cfg_env is None:
            os.environ.pop("MORTAL_CFG", None)
        else:
            os.environ["MORTAL_CFG"] = old_cfg_env

    if len(sample) != 6:
        fail(f"{mode} full dataloader returned unexpected entry size: {len(sample)}")
    reward = float(sample[4])
    rank = int(sample[5])
    if not np.isfinite(reward):
        fail(f"{mode} full dataloader produced non-finite kyoku reward: {reward}")
    if not 0 <= rank < contract["players"]:
        fail(f"{mode} full dataloader produced invalid next rank {rank} for {contract['players']} players")

    reward_source = (mortal_dir / "reward_calculator.py").read_text(encoding="utf-8")
    dataloader_source = (mortal_dir / "dataloader.py").read_text(encoding="utf-8")
    if "MORTAL_ROGS_UNIFIED_REWARD_STAGE2" not in reward_source:
        fail(f"{mode} unified reward Stage 2 marker missing")
    if "MORTAL_ROGS_UNIFIED_DATALOADER_STAGE2" not in dataloader_source:
        fail(f"{mode} unified dataloader Stage 2 marker missing")

    return {
        "reward": reward,
        "next_rank": rank,
        "players": contract["players"],
        "grp_input_size": game["grp_input_size"],
    }


def run_canonical_trainer_smoke(
    *,
    mode: str,
    contract: dict[str, int],
    logs: list[Path],
    example_cfg: Path,
    output_root: Path,
    mortal_dir: Path,
    device: str,
    toml,
    torch,
) -> dict[str, object]:
    """Run the patched upstream train.py, including FileDatasetsIter and ROGS."""

    from model import Brain, DQN

    run_root = output_root / f"canonical-{mode}"
    run_root.mkdir(parents=True, exist_ok=True)
    checkpoint = run_root / "current.pth"
    best_checkpoint = run_root / "best.pth"
    baseline_checkpoint = run_root / "baseline.pth"
    cfg_path = run_root / "config.toml"
    names_file = run_root / "players.txt"
    names_file.write_text(f"smoke-{mode}-challenger\n", encoding="utf-8")

    cfg = copy.deepcopy(toml.load(example_cfg))
    control = cfg.setdefault("control", {})
    control.update(
        {
            "version": 4,
            "online": False,
            "state_file": str(checkpoint),
            "best_state_file": str(best_checkpoint),
            "tensorboard_dir": str(run_root / "tensorboard"),
            "device": device,
            "enable_cudnn_benchmark": False,
            "enable_amp": False,
            "enable_compile": False,
            "batch_size": 64,
            "opt_step_every": 1,
            "save_every": 1,
            "test_every": 1000000,
            "submit_every": 1,
        }
    )

    game = cfg.setdefault("game", {})
    game.update(
        {
            "mode": mode,
            "num_players": contract["players"],
            "action_space": contract["actions"],
            "obs_channels": contract["obs"],
            "oracle_obs_channels": 170 if mode == "3p" else 217,
            "grp_input_size": 6 if mode == "3p" else 7,
        }
    )

    dataset_cfg = cfg.setdefault("dataset", {})
    dataset_cfg.update(
        {
            "globs": [str(logs[0])],
            "file_index": str(run_root / "file-index.pth"),
            "file_batch_size": 1,
            "reserve_ratio": 0.0,
            "num_workers": 0,
            "player_names_files": [str(names_file)],
            "num_epochs": 1,
            "enable_augmentation": False,
            "augmented_first": False,
            "pin_memory": False,
        }
    )

    cfg.setdefault("env", {})["pts"] = [6.0, 3.0, 0.0] if mode == "3p" else [6.0, 4.0, 2.0, 0.0]
    cfg.setdefault("resnet", {})["conv_channels"] = 8
    cfg["resnet"]["num_blocks"] = 1
    cfg.setdefault("freeze_bn", {})["mortal"] = False
    cfg.setdefault("grp", {})["state_file"] = str(output_root / f"probe-grp-{mode}.pth")

    cfg["rogs"] = {
        "enabled": True,
        "curriculum_steps": 100,
        "oracle_final_weight": 0.05,
        "bc_final_weight": 0.02,
        "cql_final_weight": 0.05,
        "regret_final_weight": 0.75,
    }
    cfg["objective"] = {
        "value_weight": 1.0,
        "regret_weight": 0.5,
        "teacher_kl_weight": 0.3,
        "entropy_weight": 0.002,
        "bc_anchor_weight": 0.1,
        "cql_anchor_weight": 0.25,
        "regret_clip": 12.0,
        "teacher_temperature": 1.5,
    }

    # train.py constructs TestPlayer immediately, even when test_every is far
    # away. Seed a tiny ABI-correct baseline so this smoke exercises the real
    # trainer instead of failing on config.example.toml's placeholder path.
    baseline_brain = Brain(
        version=4,
        conv_channels=8,
        num_blocks=1,
        obs_channels=contract["obs"],
    ).cpu().eval()
    baseline_dqn = DQN(version=4, action_space=contract["actions"]).cpu().eval()
    torch.save(
        {
            "config": copy.deepcopy(cfg),
            "mortal": baseline_brain.state_dict(),
            "current_dqn": baseline_dqn.state_dict(),
        },
        baseline_checkpoint,
    )
    del baseline_brain, baseline_dqn
    baseline_root = cfg.setdefault("baseline", {})
    for side_name in ("train", "test"):
        side = baseline_root.setdefault(side_name, {})
        side.update(
            {
                "device": device,
                "enable_compile": False,
                "enable_amp": False,
                "state_file": str(baseline_checkpoint),
            }
        )

    cfg_path.write_text(toml.dumps(cfg), encoding="utf-8")

    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["MORTAL_CFG"] = str(cfg_path)
    env["MORTAL_GAME_MODE"] = mode
    env["MORTAL_PLAYER_COUNT"] = str(contract["players"])
    python_path = [str(project_root), str(mortal_dir)]
    if env.get("PYTHONPATH"):
        python_path.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(python_path)

    try:
        proc = subprocess.run(
            [sys.executable, str(mortal_dir / "train.py")],
            cwd=mortal_dir,
            env=env,
            text=True,
            capture_output=True,
            timeout=180,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        fail(f"{mode} canonical trainer smoke timed out: {exc}")
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout + "\n" + proc.stderr).splitlines()[-80:])
        fail(f"{mode} canonical trainer failed with exit {proc.returncode}:\n{tail}")
    if not checkpoint.is_file():
        fail(f"{mode} canonical trainer did not save {checkpoint}")

    state = torch.load(checkpoint, weights_only=True, map_location="cpu")
    for key in ("mortal", "current_dqn", "aux_net", "optimizer", "scheduler", "steps", "config"):
        if key not in state:
            fail(f"{mode} canonical trainer checkpoint missing {key}")
    steps = int(state["steps"])
    if steps <= 0:
        fail(f"{mode} canonical trainer made no optimization steps")
    state_cfg = state["config"]
    if not bool(state_cfg.get("rogs", {}).get("enabled", False)):
        fail(f"{mode} canonical trainer checkpoint lost ROGS enablement")
    if state_cfg.get("game", {}).get("mode") != mode:
        fail(f"{mode} canonical trainer checkpoint lost game mode")

    return {
        "steps": steps,
        "checkpoint": str(checkpoint),
        "rogs_enabled": True,
        "player_filter": f"smoke-{mode}-challenger",
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Run one real-data optimization step from unified 3P/4P self-play logs and save strict v4 checkpoints."
    )
    ap.add_argument("--runtime-root", type=Path, required=True)
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--batch-size", type=int, default=16)
    args = ap.parse_args()

    if args.batch_size <= 0:
        fail("--batch-size must be positive")

    root = args.runtime_root.expanduser().resolve()
    mortal_dir = root / "mortal"
    sys.path.insert(0, str(mortal_dir))

    import toml
    import torch
    import libriichi
    from model import Brain, DQN, GRP

    dataset = libriichi.dataset
    device = torch.device(args.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        fail("CUDA training smoke requested but CUDA is unavailable")

    contracts = {
        "3p": {"actions": 44, "obs": 1010, "players": 3},
        "4p": {"actions": 46, "obs": 1012, "players": 4},
    }
    gameplay_root = root / "runtime" / "smoke-gameplay"
    output_root = root / "runtime" / "smoke-training"
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    example_cfg = mortal_dir / "config.example.toml"
    if not example_cfg.is_file():
        fail(f"missing Mortal example config: {example_cfg}")

    torch.manual_seed(0x9017)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(0x9017)

    results: dict[str, object] = {}

    for mode, c in contracts.items():
        logs = sorted((gameplay_root / mode).glob("*.json.gz"))
        if len(logs) < c["players"]:
            fail(
                f"{mode} needs self-play logs from smoke_unified_gameplay.py; "
                f"expected at least {c['players']}, got {len(logs)}"
            )

        full_dataloader = probe_full_dataloader(
            mode=mode,
            contract=c,
            logs=logs,
            example_cfg=example_cfg,
            output_root=output_root,
            mortal_dir=mortal_dir,
            toml=toml,
            torch=torch,
            GRP=GRP,
        )
        canonical_trainer = run_canonical_trainer_smoke(
            mode=mode,
            contract=c,
            logs=logs,
            example_cfg=example_cfg,
            output_root=output_root,
            mortal_dir=mortal_dir,
            device=str(device),
            toml=toml,
            torch=torch,
        )

        loader = dataset.GameplayLoader(
            version=4,
            oracle=False,
            player_names=None,
            excludes=None,
            augmented=False,
        )
        loaded_files = loader.load_gz_log_files([str(p) for p in logs])

        obs_samples: list[np.ndarray] = []
        mask_samples: list[np.ndarray] = []
        action_samples: list[int] = []
        for loaded_file in loaded_files:
            for game in loaded_file:
                obs_list = game.take_obs()
                actions = game.take_actions()
                masks = game.take_masks()
                for obs, action, mask in zip(obs_list, actions, masks, strict=True):
                    obs_arr = np.asarray(obs, dtype=np.float32)
                    mask_arr = np.asarray(mask, dtype=np.bool_)
                    action_i = int(action)
                    # Kan-selection entries use a tile-selection mask rather than
                    # the normal action ABI. They are valid training data, but are
                    # intentionally excluded from this DQN-head optimization smoke.
                    if obs_arr.shape != (c["obs"], 34):
                        continue
                    if mask_arr.shape != (c["actions"],):
                        continue
                    if not (0 <= action_i < c["actions"]):
                        continue
                    if not bool(mask_arr[action_i]):
                        continue
                    obs_samples.append(obs_arr)
                    mask_samples.append(mask_arr)
                    action_samples.append(action_i)
                    if len(obs_samples) >= args.batch_size:
                        break
                if len(obs_samples) >= args.batch_size:
                    break
            if len(obs_samples) >= args.batch_size:
                break

        if len(obs_samples) < min(4, args.batch_size):
            fail(f"{mode} produced too few normal-action samples for mini training: {len(obs_samples)}")

        obs = torch.as_tensor(np.stack(obs_samples), device=device)
        mask = torch.as_tensor(np.stack(mask_samples), device=device)
        action = torch.as_tensor(action_samples, dtype=torch.long, device=device)

        brain = Brain(
            version=4,
            conv_channels=16,
            num_blocks=1,
            obs_channels=c["obs"],
        ).to(device).train()
        dqn = DQN(version=4, action_space=c["actions"]).to(device).train()
        parameters = list(brain.parameters()) + list(dqn.parameters())
        optimizer = torch.optim.AdamW(parameters, lr=1e-3, weight_decay=0.0)

        watched = next(p for p in parameters if p.requires_grad and p.numel() > 0)
        before = watched.detach().clone()
        optimizer.zero_grad(set_to_none=True)
        phi = brain(obs)
        q = dqn(phi, mask)
        if q.shape != (len(action_samples), c["actions"]):
            fail(f"{mode} Q shape {tuple(q.shape)} does not match action ABI")
        target_q = q.gather(1, action[:, None]).squeeze(1)
        log_norm = torch.logsumexp(q, dim=1)
        loss = -(target_q - log_norm).mean()
        if not bool(torch.isfinite(loss)):
            fail(f"{mode} mini-training loss is non-finite: {loss.item()}")
        loss.backward()

        finite_grad = False
        nonzero_grad = False
        for p in parameters:
            if p.grad is None:
                continue
            if not bool(torch.isfinite(p.grad).all()):
                fail(f"{mode} mini-training produced non-finite gradients")
            finite_grad = True
            if bool(torch.count_nonzero(p.grad)):
                nonzero_grad = True
        if not finite_grad or not nonzero_grad:
            fail(f"{mode} mini-training produced no usable gradient")

        optimizer.step()
        changed = not torch.equal(before, watched.detach())
        if not changed:
            fail(f"{mode} optimizer step did not change model parameters")

        source_cfg = mortal_dir / f"config.{mode}.toml"
        cfg_source = source_cfg if source_cfg.is_file() else example_cfg
        cfg = copy.deepcopy(toml.load(cfg_source))
        cfg.setdefault("control", {})["version"] = 4
        cfg.setdefault("game", {})["mode"] = mode
        cfg["game"]["num_players"] = c["players"]
        cfg["game"]["action_space"] = c["actions"]
        cfg["game"]["obs_channels"] = c["obs"]
        cfg.setdefault("resnet", {})["conv_channels"] = 16
        cfg["resnet"]["num_blocks"] = 1

        checkpoint = output_root / f"smoke-trained-{mode}.pth"
        brain.eval()
        dqn.eval()
        torch.save(
            {
                "config": cfg,
                "mortal": brain.state_dict(),
                "current_dqn": dqn.state_dict(),
                "smoke_training": {
                    "mode": mode,
                    "samples": len(action_samples),
                    "loss": float(loss.detach().cpu()),
                    "source_logs": [str(p) for p in logs],
                    "full_dataloader": full_dataloader,
                    "canonical_trainer": canonical_trainer,
                },
            },
            checkpoint,
        )

        state = torch.load(checkpoint, weights_only=True, map_location="cpu")
        state_cfg = state["config"]
        if int(state_cfg["control"]["version"]) != 4:
            fail(f"{mode} trained checkpoint lost v4 ABI")
        if state_cfg["game"]["mode"] != mode:
            fail(f"{mode} trained checkpoint mode mismatch")
        if int(state_cfg["game"]["action_space"]) != c["actions"]:
            fail(f"{mode} trained checkpoint action-space mismatch")
        if int(state_cfg["game"]["obs_channels"]) != c["obs"]:
            fail(f"{mode} trained checkpoint observation ABI mismatch")

        reload_brain = Brain(
            version=4,
            conv_channels=16,
            num_blocks=1,
            obs_channels=c["obs"],
        ).eval()
        reload_dqn = DQN(version=4, action_space=c["actions"]).eval()
        reload_brain.load_state_dict(state["mortal"], strict=True)
        reload_dqn.load_state_dict(state["current_dqn"], strict=True)

        with torch.inference_mode():
            probe_obs = obs[:1].detach().cpu()
            probe_mask = mask[:1].detach().cpu()
            probe_q = reload_dqn(reload_brain(probe_obs), probe_mask)
        if probe_q.shape != (1, c["actions"]):
            fail(f"{mode} strict-reloaded checkpoint Q shape mismatch: {tuple(probe_q.shape)}")
        legal_probe = probe_q[probe_mask]
        if legal_probe.numel() == 0 or not bool(torch.isfinite(legal_probe).all()):
            fail(f"{mode} strict-reloaded checkpoint produced invalid legal Q values")

        results[mode] = {
            "logs": len(logs),
            "samples": len(action_samples),
            "loss": float(loss.detach().cpu()),
            "parameter_changed": changed,
            "checkpoint": str(checkpoint),
            "strict_reload": True,
            "action_space": c["actions"],
            "obs": [c["obs"], 34],
            "full_dataloader": full_dataloader,
            "canonical_trainer": canonical_trainer,
        }

        del loader, loaded_files, obs, mask, action, brain, dqn, reload_brain, reload_dqn, state
        if device.type == "cuda":
            torch.cuda.empty_cache()
            torch.cuda.synchronize(device)

    print("MORTAL_UNIFIED_FULL_DATALOADER_REWARD_E2E_OK")
    print("MORTAL_UNIFIED_CANONICAL_TRAINER_ROGS_E2E_OK")
    print("MORTAL_UNIFIED_REAL_DATA_TRAINING_E2E_OK")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
