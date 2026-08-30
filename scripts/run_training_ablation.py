from __future__ import annotations

import argparse
import json
import os
import random
import runpy
import shutil
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _expected_python(runtime_root: Path) -> Path:
    if os.name == "nt":
        return runtime_root / ".venv" / "Scripts" / "python.exe"
    return runtime_root / ".venv" / "bin" / "python"


def _seed_everything(seed: int) -> None:
    import numpy as np
    import torch

    random.seed(seed)
    np.random.seed(seed % (2**32))
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one isolated Mortal-vs-ROGS training ablation from the unified runtime."
    )
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--mode", choices=("3p", "4p"), required=True)
    parser.add_argument("--variant", choices=("mortal", "rogs", "rogs-global"), required=True)
    parser.add_argument("--seed", type=int, default=0x9017)
    parser.add_argument("--prepare-only", action="store_true")
    resume_group = parser.add_mutually_exclusive_group()
    resume_group.add_argument("--fresh", action="store_true")
    resume_group.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    root = args.runtime_root.expanduser().resolve()
    mortal_dir = root / "mortal"
    base_config = mortal_dir / f"config.{args.mode}.toml"
    if not mortal_dir.is_dir() or not base_config.is_file():
        raise SystemExit(f"Unified Mortal runtime/config is missing under {root}")

    expected_python = _expected_python(root)
    if not expected_python.is_file():
        raise SystemExit(f"Unified runtime Python is missing: {expected_python}")
    try:
        running_python = Path(sys.executable).resolve()
        expected_resolved = expected_python.resolve()
    except OSError:
        running_python = Path(sys.executable)
        expected_resolved = expected_python
    if running_python != expected_resolved:
        raise SystemExit(
            "Run this ablation with the unified runtime Python: "
            f'"{expected_python}" "{Path(__file__).resolve()}" '
            f'--runtime-root "{root}" --mode {args.mode} --variant {args.variant} --seed {args.seed}'
        )

    from app.configuration import build_training_ablation_config, read_toml, write_toml

    mode_root = root / "runtime" / args.mode
    cfg = build_training_ablation_config(
        read_toml(base_config),
        mode=args.mode,
        variant=args.variant,
        seed=args.seed,
        mode_root=mode_root,
    )
    experiment = cfg["experiment"]
    model_dir = Path(experiment["model_dir"])
    run_dir = Path(experiment["run_dir"])
    checkpoint = Path(cfg["control"]["state_file"])

    if args.fresh:
        for path in (model_dir, run_dir):
            if path.exists():
                shutil.rmtree(path)
    elif checkpoint.exists() and not args.resume:
        raise SystemExit(
            f"Ablation checkpoint already exists: {checkpoint}. Use --resume or --fresh explicitly."
        )

    model_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)
    config_path = run_dir / "config.toml"
    experiment["source_config"] = str(base_config)
    experiment["config_path"] = str(config_path)
    write_toml(config_path, cfg, make_backup=False)

    manifest = {
        "protocol": "mortal-rogs-training-ablation-v1",
        "mode": args.mode,
        "variant": args.variant,
        "seed": int(args.seed),
        "source_config": str(base_config),
        "config": str(config_path),
        "checkpoint": str(checkpoint),
        "rogs_enabled": bool(cfg.get("rogs", {}).get("enabled", False)),
        "global_reward_enabled": bool(cfg.get("global_reward", {}).get("enabled", False)),
    }
    (run_dir / "experiment.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("MORTAL_TRAINING_ABLATION_PREPARED", json.dumps(manifest, ensure_ascii=False))
    if args.prepare_only:
        return 0

    _seed_everything(int(args.seed))
    os.environ["PYTHONHASHSEED"] = str(int(args.seed))
    os.environ["MORTAL_CFG"] = str(config_path)
    os.environ["MORTAL_GAME_MODE"] = args.mode
    os.environ["MORTAL_PLAYER_COUNT"] = "3" if args.mode == "3p" else "4"
    existing = os.environ.get("PYTHONPATH", "")
    path_parts = [str(PROJECT_ROOT), str(mortal_dir)]
    if existing:
        path_parts.append(existing)
    os.environ["PYTHONPATH"] = os.pathsep.join(path_parts)
    if str(mortal_dir) not in sys.path:
        sys.path.insert(0, str(mortal_dir))

    previous_cwd = Path.cwd()
    try:
        os.chdir(mortal_dir)
        runpy.run_path(str(mortal_dir / "train.py"), run_name="__main__")
    finally:
        os.chdir(previous_cwd)

    if not checkpoint.is_file():
        raise RuntimeError(f"Ablation finished without checkpoint: {checkpoint}")
    print(
        "MORTAL_TRAINING_ABLATION_OK",
        f"mode={args.mode}",
        f"variant={args.variant}",
        f"seed={args.seed}",
        f"checkpoint={checkpoint}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
