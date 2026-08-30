from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def fail(msg: str) -> None:
    raise RuntimeError(msg)


def main() -> int:
    ap = argparse.ArgumentParser(description="Strict-save/load and evaluator E2E for unified 3P/4P Mortal v4 checkpoints.")
    ap.add_argument("--runtime-root", type=Path, required=True)
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--trained-checkpoint-root", type=Path, default=None)
    ap.add_argument("--require-trained-checkpoints", action="store_true")
    args = ap.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    root = args.runtime_root.expanduser().resolve()
    mortal_dir = root / "mortal"
    sys.path.insert(0, str(mortal_dir))

    import toml
    import torch
    from evaluation.paired import load_paired_records
    from model import Brain, DQN

    device = torch.device(args.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        fail("CUDA evaluator smoke requested but CUDA is unavailable")

    contracts = {
        "3p": {"actions": 44, "obs": 1010, "evaluator": "one_vs_two.py", "section": "1v2", "games": 3},
        "4p": {"actions": 46, "obs": 1012, "evaluator": "one_vs_three.py", "section": "1v3", "games": 4},
    }
    smoke_root = root / "runtime" / "smoke-evaluator"
    if smoke_root.exists():
        shutil.rmtree(smoke_root)
    smoke_root.mkdir(parents=True, exist_ok=True)
    trained_root = (
        args.trained_checkpoint_root.expanduser().resolve()
        if args.trained_checkpoint_root is not None
        else root / "runtime" / "smoke-training"
    )
    results: dict[str, object] = {}

    example_cfg = mortal_dir / "config.example.toml"
    if not example_cfg.is_file():
        fail(f"missing Mortal example config: {example_cfg}")

    paired_script = project_root / "scripts" / "build_paired_evaluation.py"
    if not paired_script.is_file():
        fail(f"paired evaluation builder is missing: {paired_script}")

    for mode, c in contracts.items():
        trained_checkpoint = trained_root / f"smoke-trained-{mode}.pth"
        if trained_checkpoint.is_file():
            checkpoint = trained_checkpoint
            state = torch.load(checkpoint, weights_only=True, map_location="cpu")
            checkpoint_source = "real-data-mini-training"
            if "smoke_training" not in state:
                fail(f"{mode} trained checkpoint is missing smoke_training metadata")
        else:
            if args.require_trained_checkpoints:
                fail(f"required trained checkpoint is missing: {trained_checkpoint}")
            source_cfg = mortal_dir / f"config.{mode}.toml"
            cfg_source = source_cfg if source_cfg.is_file() else example_cfg
            cfg = copy.deepcopy(toml.load(cfg_source))
            cfg.setdefault("control", {})["version"] = 4
            cfg["control"]["enable_compile"] = False
            cfg.setdefault("game", {})["mode"] = mode
            cfg["game"]["num_players"] = 3 if mode == "3p" else 4
            cfg["game"]["action_space"] = c["actions"]
            cfg["game"]["obs_channels"] = c["obs"]
            cfg.setdefault("resnet", {})["conv_channels"] = 16
            cfg["resnet"]["num_blocks"] = 1

            brain = Brain(version=4, conv_channels=16, num_blocks=1, obs_channels=c["obs"]).eval()
            dqn = DQN(version=4, action_space=c["actions"]).eval()
            checkpoint = smoke_root / f"smoke-{mode}.pth"
            torch.save(
                {
                    "config": cfg,
                    "mortal": brain.state_dict(),
                    "current_dqn": dqn.state_dict(),
                },
                checkpoint,
            )
            state = torch.load(checkpoint, weights_only=True, map_location="cpu")
            checkpoint_source = "generated-fallback"
            del brain, dqn

        state_cfg = state["config"]
        if int(state_cfg["control"]["version"]) != 4:
            fail(f"{mode} checkpoint version is not v4")
        if state_cfg["game"]["mode"] != mode:
            fail(f"{mode} checkpoint game.mode mismatch")
        if int(state_cfg["game"]["action_space"]) != c["actions"]:
            fail(f"{mode} checkpoint action-space mismatch")
        if int(state_cfg["game"]["obs_channels"]) != c["obs"]:
            fail(f"{mode} checkpoint obs-channel mismatch")

        conv_channels = int(state_cfg["resnet"]["conv_channels"])
        num_blocks = int(state_cfg["resnet"]["num_blocks"])
        brain2 = Brain(
            version=4,
            conv_channels=conv_channels,
            num_blocks=num_blocks,
            obs_channels=c["obs"],
        ).eval()
        dqn2 = DQN(version=4, action_space=c["actions"]).eval()
        brain2.load_state_dict(state["mortal"], strict=True)
        dqn2.load_state_dict(state["current_dqn"], strict=True)

        cfg = copy.deepcopy(state_cfg)
        cfg.setdefault("control", {})["enable_compile"] = False
        section = cfg.setdefault(c["section"], {})
        section["games_per_iter"] = c["games"]
        section["iters"] = 1
        section["seed_start"] = 23000 if mode == "3p" else 24000
        section["seed_key"] = 0xE812
        log_dir = smoke_root / f"logs-{mode}"
        section["log_dir"] = str(log_dir)
        if mode == "4p":
            section.setdefault("akochan", {})["enabled"] = False
        for side, name in (("challenger", f"eval-{mode}-challenger"), ("champion", f"eval-{mode}-champion")):
            side_cfg = section.setdefault(side, {})
            side_cfg["state_file"] = str(checkpoint)
            side_cfg["device"] = str(device)
            side_cfg["enable_amp"] = False
            side_cfg["enable_compile"] = False
            side_cfg["enable_rule_based_agari_guard"] = True
            side_cfg["name"] = name

        eval_cfg = smoke_root / f"eval-{mode}.toml"
        eval_cfg.write_text(toml.dumps(cfg), encoding="utf-8")
        env = os.environ.copy()
        env["MORTAL_CFG"] = str(eval_cfg)
        env["MORTAL_GAME_MODE"] = mode
        old_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = str(mortal_dir) if not old_pythonpath else os.pathsep.join((str(mortal_dir), old_pythonpath))
        proc = subprocess.run(
            [sys.executable, c["evaluator"]],
            cwd=mortal_dir,
            env=env,
            text=True,
            capture_output=True,
        )
        if proc.returncode != 0:
            fail(
                f"{mode} evaluator failed with exit {proc.returncode}\n"
                f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
            )
        logs = sorted(log_dir.glob("*.json.gz"))
        if len(logs) != c["games"]:
            fail(f"{mode} evaluator expected {c['games']} logs, got {len(logs)} in {log_dir}")

        # Feed real native duplicate logs through the exact paired-evaluation
        # bridge. Using the same directory on both sides gives an invariant
        # zero-delta comparison while still exercising filename seed/seat
        # matching, MJAI score reconstruction, JSONL compatibility, and the
        # Mortal-docs-style strength summary for both 3P and 4P.
        paired_output = smoke_root / f"paired-{mode}.jsonl"
        pair_proc = subprocess.run(
            [
                sys.executable,
                str(paired_script),
                "--candidate-dir",
                str(log_dir),
                "--baseline-dir",
                str(log_dir),
                "--mode",
                mode,
                "--output",
                str(paired_output),
                "--candidate-name",
                f"smoke-{mode}-candidate",
                "--baseline-name",
                f"smoke-{mode}-baseline",
                "--room",
                "smoke",
                "--rank",
                "smoke",
            ],
            cwd=project_root,
            env=env,
            text=True,
            capture_output=True,
        )
        if pair_proc.returncode != 0:
            fail(
                f"{mode} paired evaluation builder failed with exit {pair_proc.returncode}\n"
                f"STDOUT:\n{pair_proc.stdout}\nSTDERR:\n{pair_proc.stderr}"
            )
        paired_rows = load_paired_records(paired_output)
        if len(paired_rows) != c["games"]:
            fail(f"{mode} paired evaluation expected {c['games']} rows, got {len(paired_rows)}")
        for row in paired_rows:
            if row.candidate != row.baseline:
                fail(f"{mode} identical-log paired comparison produced non-zero side drift: {row}")

        summary_json = paired_output.with_suffix(".summary.json")
        summary_md = paired_output.with_suffix(".summary.md")
        if not summary_json.is_file() or not summary_md.is_file():
            fail(f"{mode} strength summary outputs are missing")
        strength = json.loads(summary_json.read_text(encoding="utf-8"))
        deltas = strength.get("candidate_minus_baseline", {})
        for metric in ("avg_rank", "avg_rank_pt", "avg_game_delta_score", "tobi_rate"):
            if float(deltas.get(metric, float("nan"))) != 0.0:
                fail(f"{mode} identical-log strength metric {metric} is not zero: {deltas}")

        results[mode] = {
            "checkpoint": str(checkpoint),
            "checkpoint_source": checkpoint_source,
            "strict_load": True,
            "evaluator": c["evaluator"],
            "games": c["games"],
            "logs": len(logs),
            "paired_rows": len(paired_rows),
            "paired_output": str(paired_output),
            "strength_summary": str(summary_json),
            "stdout_tail": proc.stdout.strip().splitlines()[-3:],
        }
        del brain2, dqn2, state

    print("MORTAL_UNIFIED_CHECKPOINT_EVAL_E2E_OK")
    print("MORTAL_UNIFIED_EVALUATOR_E2E_OK")
    print("MORTAL_UNIFIED_PAIRED_STRENGTH_E2E_OK")
    if args.require_trained_checkpoints:
        print("MORTAL_UNIFIED_TRAINED_CHECKPOINT_EVAL_E2E_OK")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
