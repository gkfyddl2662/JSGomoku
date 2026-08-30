from __future__ import annotations

import copy
import shutil
from pathlib import Path
from typing import Any

import toml


class ConfigError(RuntimeError):
    pass


TRAINING_ABLATION_VARIANTS: dict[str, tuple[bool, bool]] = {
    "mortal": (False, False),
    "rogs": (True, False),
    "rogs-global": (True, True),
}


def read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Config not found: {path}")
    return toml.load(path)


def write_toml(path: Path, data: dict[str, Any], make_backup: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if make_backup and path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".webui.bak"))
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(toml.dumps(data), encoding="utf-8")
    temp.replace(path)


def load_preset(project_root: Path, name: str = "rtx5080", mode: str = "3p") -> dict[str, Any]:
    suffix = "sanma" if mode == "3p" else "yonma"
    path = project_root / "config" / f"{name}.{suffix}.toml"
    if not path.exists():
        raise ConfigError(f"Unknown {mode} preset: {name}")
    return toml.load(path)


def merge_preset(current: dict[str, Any], preset: dict[str, Any]) -> dict[str, Any]:
    result = dict(current)
    _deep_merge(result, preset)
    return result


def build_training_ablation_config(
    current: dict[str, Any],
    *,
    mode: str,
    variant: str,
    seed: int,
    mode_root: Path,
) -> dict[str, Any]:
    """Clone one runtime config into an isolated, fair offline ablation run."""

    normalized_mode = str(mode).casefold().strip()
    if normalized_mode not in {"3p", "4p"}:
        raise ConfigError(f"Unsupported ablation mode: {mode!r}")
    variant = str(variant).casefold().strip()
    if variant not in TRAINING_ABLATION_VARIANTS:
        choices = ", ".join(TRAINING_ABLATION_VARIANTS)
        raise ConfigError(f"Unknown training ablation variant {variant!r}; choose {choices}")
    if int(seed) < 0:
        raise ConfigError("Training ablation seed must be non-negative")

    cfg = copy.deepcopy(current)
    game = cfg.setdefault("game", {})
    configured = str(game.get("mode", normalized_mode)).casefold().strip()
    aliases = {"3": "3p", "sanma": "3p", "4": "4p", "yonma": "4p"}
    configured = aliases.get(configured, configured)
    if configured != normalized_mode:
        raise ConfigError(
            f"Base config game.mode={configured!r} does not match requested {normalized_mode!r}"
        )
    game["mode"] = normalized_mode

    rogs_enabled, global_reward_enabled = TRAINING_ABLATION_VARIANTS[variant]
    cfg.setdefault("rogs", {})["enabled"] = rogs_enabled
    cfg.setdefault("global_reward", {})["enabled"] = global_reward_enabled

    seed_dir = f"seed-{int(seed)}"
    mode_root = mode_root.expanduser().resolve()
    model_dir = mode_root / "models" / "ablation" / seed_dir / variant
    run_dir = mode_root / "runs" / "ablation" / seed_dir / variant

    control = cfg.setdefault("control", {})
    control["online"] = False
    control["training_seed"] = int(seed)
    control["state_file"] = str(model_dir / "current.pth")
    control["best_state_file"] = str(model_dir / "best_mortal.pth")
    control["tensorboard_dir"] = str(run_dir / "tensorboard")

    cfg.setdefault("test_play", {})["log_dir"] = str(run_dir / "test_play")
    cfg["experiment"] = {
        "kind": "training_ablation",
        "variant": variant,
        "seed": int(seed),
        "mode": normalized_mode,
        "rogs_enabled": rogs_enabled,
        "global_reward_enabled": global_reward_enabled,
        "model_dir": str(model_dir),
        "run_dir": str(run_dir),
    }
    return cfg


def _deep_merge(dst: dict[str, Any], src: dict[str, Any]) -> None:
    for key, value in src.items():
        if isinstance(value, dict) and isinstance(dst.get(key), dict):
            _deep_merge(dst[key], value)
        else:
            dst[key] = value
