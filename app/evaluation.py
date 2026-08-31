from __future__ import annotations

from pathlib import Path
import shutil
import tomllib
from typing import Any

from evaluation.backends import BACKENDS, select_backend


def evaluation_status(project_root: Path) -> dict[str, Any]:
    cfg_path = project_root / "config" / "evaluation_backends.toml"
    with cfg_path.open("rb") as f:
        cfg = tomllib.load(f)

    policy = cfg.get("evaluation", {})
    selected_3p = select_backend(3, str(policy.get("primary_3p", "auto")))
    selected_4p = select_backend(4, str(policy.get("primary_4p", "auto")))

    return {
        "config_path": str(cfg_path),
        "primary": {
            "3p": selected_3p.__dict__,
            "4p": selected_4p.__dict__,
        },
        "backends": {name: caps.__dict__ for name, caps in BACKENDS.items()},
        "runtime": {
            "wsl_available": shutil.which("wsl.exe") is not None or shutil.which("wsl") is not None,
            "mjx_ref": cfg.get("mjx", {}).get("ref", "v0.1.0"),
            "mjx_runtime": cfg.get("mjx", {}).get("runtime", "wsl2"),
            "mjx_python": cfg.get("mjx", {}).get("python", "3.11"),
        },
        "gate": cfg.get("gate", {}),
    }
