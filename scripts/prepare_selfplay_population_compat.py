from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import prepare_selfplay_population as base
from scripts.akagi_3p_compat import (
    LEGACY_3P_ACTION_SPACE,
    LEGACY_3P_OBS_CHANNELS,
    apply_runtime_evaluator,
    checkpoint_obs_channels,
    ensure_akagi_3p_compat,
)
from scripts.patch_mortal_akagi_legacy_events import apply as apply_legacy_event_adapter

_ORIGINAL_VALIDATE = base.validate_checkpoint


def _legacy_forward_probe(*, runtime_root: Path, checkpoint: Path, device: str) -> dict[str, object]:
    started = time.monotonic()
    import importlib.util
    import torch

    paths = base.runtime_paths(runtime_root, "3p")
    model_py = paths["mortal"] / "model.py"
    name = f"_mortal_rogs_legacy_probe_{abs(hash(str(model_py)))}"
    spec = importlib.util.spec_from_file_location(name, model_py)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load unified Mortal model module: {model_py}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)

    state = torch.load(checkpoint, map_location="cpu", weights_only=False)
    cfg = state["config"]
    version = int(cfg["control"].get("version", -1))
    if version != 4:
        raise ValueError(f"Akagi-compatible 3P checkpoint must be Mortal v4, got v{version}")
    conv_channels = int(cfg["resnet"]["conv_channels"])
    num_blocks = int(cfg["resnet"]["num_blocks"])
    Brain = getattr(module, "Brain")
    DQN = getattr(module, "DQN")
    brain = Brain(
        version=version,
        conv_channels=conv_channels,
        num_blocks=num_blocks,
        obs_channels=LEGACY_3P_OBS_CHANNELS,
    ).eval()
    dqn = DQN(version=version, action_space=LEGACY_3P_ACTION_SPACE).eval()
    brain.load_state_dict(state["mortal"], strict=True)
    dqn.load_state_dict(state["current_dqn"], strict=True)

    requested = device.strip().casefold()
    if requested == "auto":
        requested = "cuda:0" if torch.cuda.is_available() else "cpu"
    dev = torch.device(requested)
    if dev.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA legacy 3P probe requested but CUDA is unavailable")
    brain = brain.to(dev)
    dqn = dqn.to(dev)
    with torch.inference_mode():
        obs = torch.zeros((2, LEGACY_3P_OBS_CHANNELS, 34), device=dev)
        masks = torch.ones((2, LEGACY_3P_ACTION_SPACE), dtype=torch.bool, device=dev)
        q = dqn(brain(obs), masks)
    if tuple(q.shape) != (2, LEGACY_3P_ACTION_SPACE) or not bool(torch.isfinite(q).all()):
        raise RuntimeError(f"legacy 3P forward probe failed: q={tuple(q.shape)}")
    elapsed = time.monotonic() - started
    return {
        "seconds": round(elapsed, 3),
        "tail": [
            "MORTAL_AKAGI3P_LEGACY_FORWARD_OK "
            f"obs={LEGACY_3P_OBS_CHANNELS} actions={LEGACY_3P_ACTION_SPACE} device={dev}"
        ],
    }


def _legacy_gameplay_probe(
    *,
    runtime_root: Path,
    checkpoint: Path,
    device: str,
    smoke_seed: int,
) -> dict[str, object]:
    paths = base.runtime_paths(runtime_root, "3p")
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    parts = [str(base.PROJECT_ROOT), str(paths["mortal"])]
    if existing:
        parts.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    env["MORTAL_CFG"] = str(paths["config"])
    env["MORTAL_GAME_MODE"] = "3p"
    env["MORTAL_PLAYER_COUNT"] = "3"

    with tempfile.TemporaryDirectory(prefix="mortal-rogs-3p-akagi-checkpoint-smoke-") as td:
        temp = Path(td)
        shadow = temp / f"{checkpoint.stem}.shadow.pth"
        try:
            os.link(checkpoint, shadow)
        except OSError:
            shutil.copy2(checkpoint, shadow)
        cmd = [
            str(paths["python"]),
            str(base.PROJECT_ROOT / "scripts" / "run_model_comparison.py"),
            "--runtime-root",
            str(paths["root"]),
            "--mode",
            "3p",
            "--candidate",
            str(checkpoint),
            "--baseline",
            str(shadow),
            "--candidate-name",
            "probe-original",
            "--baseline-name",
            "probe-shadow",
            "--seed-start",
            str(smoke_seed),
            "--seed-count",
            "1",
            "--output-root",
            str(temp / "comparison"),
            "--device",
            device,
            "--no-compile",
            "--fresh",
        ]
        cmd.append("--no-amp" if device.casefold().startswith("cpu") else "--amp")
        return base._run_checked(cmd, cwd=base.PROJECT_ROOT, env=env, label="3p Akagi legacy gameplay smoke")


def validate_checkpoint_compat(
    *,
    runtime_root: Path,
    mode: str,
    checkpoint: Path,
    device: str,
    gameplay_smoke: bool,
    smoke_seed: int,
) -> dict[str, object]:
    obs_channels = checkpoint_obs_channels(checkpoint)
    if mode != "3p" or obs_channels != LEGACY_3P_OBS_CHANNELS:
        result = _ORIGINAL_VALIDATE(
            runtime_root=runtime_root,
            mode=mode,
            checkpoint=checkpoint,
            device=device,
            gameplay_smoke=gameplay_smoke,
            smoke_seed=smoke_seed,
        )
        result["abi_kind"] = "native"
        result["obs_channels"] = obs_channels
        return result

    ensure_akagi_3p_compat(runtime_root)
    apply_runtime_evaluator(runtime_root, base.PROJECT_ROOT)
    apply_legacy_event_adapter(runtime_root)
    result: dict[str, object] = {
        "abi_kind": "akagi-legacy-775",
        "obs_channels": LEGACY_3P_OBS_CHANNELS,
        "action_space": LEGACY_3P_ACTION_SPACE,
        "abi_forward": _legacy_forward_probe(
            runtime_root=runtime_root,
            checkpoint=checkpoint,
            device=device,
        ),
        "gameplay": None,
    }
    if gameplay_smoke:
        result["gameplay"] = _legacy_gameplay_probe(
            runtime_root=runtime_root,
            checkpoint=checkpoint,
            device=device,
            smoke_seed=smoke_seed,
        )
    return result


def main() -> int:
    base.validate_checkpoint = validate_checkpoint_compat
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
