from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import toml


class ConfigError(RuntimeError):
    pass


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


def _deep_merge(dst: dict[str, Any], src: dict[str, Any]) -> None:
    for key, value in src.items():
        if isinstance(value, dict) and isinstance(dst.get(key), dict):
            _deep_merge(dst[key], value)
        else:
            dst[key] = value
