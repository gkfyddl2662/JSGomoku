from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

AKAGI_REPO = "https://github.com/Xe-Persistent/Akagi-NG.git"
AKAGI_PIN = "11c0ffc0d70bf8142585b92405b4412976c9e205"
COMPAT_PROTOCOL = "mortal-rogs-akagi-3p-compat-v1"
LEGACY_3P_OBS_CHANNELS = 775
LEGACY_3P_ACTION_SPACE = 44


def checkpoint_obs_channels(path: Path) -> int:
    import torch

    state = torch.load(path.expanduser().resolve(), map_location="cpu", weights_only=False)
    try:
        weight = state["mortal"]["encoder.net.0.weight"]
    except (KeyError, TypeError) as exc:
        raise ValueError("checkpoint does not contain mortal.encoder.net.0.weight") from exc
    if getattr(weight, "ndim", None) != 3:
        raise ValueError(f"unexpected encoder.net.0.weight shape: {getattr(weight, 'shape', None)}")
    return int(weight.shape[1])


def _run(cmd: list[str], *, cwd: Path | None = None) -> str:
    proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout + "\n" + proc.stderr).strip().splitlines()[-40:])
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}\n{tail}")
    return proc.stdout.strip()


def _sha256(path: Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _binary_name() -> tuple[str, str]:
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError(
            f"Akagi-NG pinned libriichi3p binary requires Python 3.12, got {sys.version_info.major}.{sys.version_info.minor}"
        )
    machine = platform.machine().casefold()
    if machine in {"amd64", "x86_64"}:
        arch = "x86_64"
    elif machine in {"arm64", "aarch64"}:
        arch = "aarch64"
    else:
        raise RuntimeError(f"unsupported CPU architecture for pinned Akagi-NG binary: {platform.machine()}")

    if sys.platform == "win32":
        suffix = "pyd"
        triple = "pc-windows-msvc"
    elif sys.platform == "linux":
        suffix = "so"
        triple = "unknown-linux-gnu"
    elif sys.platform == "darwin":
        suffix = "so"
        triple = "apple-darwin"
    else:
        raise RuntimeError(f"unsupported platform for pinned Akagi-NG binary: {sys.platform}")
    return f"libriichi3p-3.12-{arch}-{triple}.{suffix}", f"libriichi3p.{suffix}"


def ensure_akagi_3p_compat(runtime_root: Path) -> Path:
    root = runtime_root.expanduser().resolve()
    external = root / "external" / "Akagi-NG"
    if not (external / ".git").is_dir():
        external.parent.mkdir(parents=True, exist_ok=True)
        if external.exists():
            shutil.rmtree(external)
        _run(["git", "clone", "--no-checkout", AKAGI_REPO, str(external)])

    _run(["git", "fetch", "--depth", "1", "origin", AKAGI_PIN], cwd=external)
    _run(["git", "checkout", "--detach", "--force", AKAGI_PIN], cwd=external)
    actual = _run(["git", "rev-parse", "HEAD"], cwd=external)
    if actual != AKAGI_PIN:
        raise RuntimeError(f"Akagi-NG pin mismatch: expected {AKAGI_PIN}, got {actual}")

    source_name, target_name = _binary_name()
    source = external / "lib" / source_name
    if not source.is_file():
        raise RuntimeError(f"pinned Akagi-NG libriichi3p binary not found: {source}")

    compat_dir = root / "compat" / "akagi-ng" / "lib"
    compat_dir.mkdir(parents=True, exist_ok=True)
    target = compat_dir / target_name
    source_sha = _sha256(source)
    if not target.is_file() or _sha256(target) != source_sha:
        tmp = target.with_suffix(target.suffix + ".tmp")
        shutil.copy2(source, tmp)
        tmp.replace(target)

    manifest = {
        "protocol": COMPAT_PROTOCOL,
        "repository": AKAGI_REPO,
        "commit": AKAGI_PIN,
        "source": str(source),
        "binary": str(target),
        "sha256": source_sha,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "platform": sys.platform,
        "machine": platform.machine(),
    }
    manifest_path = compat_dir.parent / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "MORTAL_AKAGI3P_COMPAT_READY",
        f"pin={AKAGI_PIN[:12]}",
        f"binary={target}",
        flush=True,
    )
    return target


def apply_runtime_evaluator(runtime_root: Path, project_root: Path | None = None) -> None:
    root = runtime_root.expanduser().resolve()
    project = (project_root or Path(__file__).resolve().parents[1]).expanduser().resolve()
    python = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    patcher = project / "scripts" / "patch_mortal_unified_eval_stage5c.py"
    if not python.is_file() or not patcher.is_file():
        raise RuntimeError("unified runtime Python or Stage 5C patcher is missing")
    _run([str(python), str(patcher), "--root", str(root)], cwd=project)


__all__ = [
    "AKAGI_PIN",
    "COMPAT_PROTOCOL",
    "LEGACY_3P_ACTION_SPACE",
    "LEGACY_3P_OBS_CHANNELS",
    "apply_runtime_evaluator",
    "checkpoint_obs_channels",
    "ensure_akagi_3p_compat",
]
