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


def _run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> str:
    proc = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout + "\n" + proc.stderr).strip().splitlines()[-40:])
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}\n{tail}")
    return proc.stdout.strip()


def _run_stream(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> None:
    proc = subprocess.run(cmd, cwd=cwd, env=env, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}")


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


def _runtime_python(root: Path) -> Path:
    python = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        raise RuntimeError(f"unified runtime Python is missing: {python}")
    return python


def _validate_pinned_binary(root: Path, compat_dir: Path) -> None:
    python = _runtime_python(root)
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(compat_dir) + (os.pathsep + existing if existing else "")
    code = (
        "import libriichi3p; "
        "assert tuple(libriichi3p.consts.obs_shape(4)) == (775, 34); "
        "assert int(libriichi3p.consts.ACTION_SPACE) == 44; "
        "assert hasattr(libriichi3p, 'mjai') and hasattr(libriichi3p.mjai, 'Bot'); "
        "print('MORTAL_AKAGI3P_BINARY_OK obs=775 actions=44 mjai=Bot')"
    )
    output = _run([str(python), "-c", code], cwd=root, env=env)
    if output:
        print(output, flush=True)


def _probe_unified_3p_arena(root: Path) -> str:
    python = _runtime_python(root)
    code = (
        "from libriichi.arena import OneVsTwo; "
        "print('MORTAL_UNIFIED_3P_ARENA_READY source=installed-unified-libriichi')"
    )
    return _run([str(python), "-c", code], cwd=root)


def _rebuild_unified_3p_arena(root: Path, project: Path) -> None:
    print("MORTAL_UNIFIED_3P_ARENA_REBUILD reason=missing-or-stale-extension", flush=True)
    if os.name == "nt":
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if not powershell:
            raise RuntimeError("PowerShell is required to rebuild unified libriichi on Windows")
        script = project / "scripts" / "rebuild_unified_libriichi.ps1"
        if not script.is_file():
            raise RuntimeError(f"unified libriichi rebuild helper is missing: {script}")
        _run_stream(
            [
                powershell,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-InstallRoot",
                str(root),
            ],
            cwd=project,
        )
        return

    python = _runtime_python(root)
    patcher = project / "scripts" / "patch_mortal_unified_all.py"
    _run_stream([str(python), str(patcher), "--root", str(root)], cwd=project)
    libriichi = root / "libriichi"
    if not libriichi.is_dir():
        raise RuntimeError(f"unified libriichi source is missing: {libriichi}")
    try:
        _run([str(python), "-m", "maturin", "--version"], cwd=libriichi)
    except RuntimeError:
        _run_stream([str(python), "-m", "pip", "install", "maturin"], cwd=project)
    _run_stream([str(python), "-m", "maturin", "develop", "--release"], cwd=libriichi)


def ensure_unified_3p_arena(runtime_root: Path, project_root: Path | None = None) -> None:
    root = runtime_root.expanduser().resolve()
    project = (project_root or Path(__file__).resolve().parents[1]).expanduser().resolve()
    try:
        output = _probe_unified_3p_arena(root)
    except RuntimeError:
        _rebuild_unified_3p_arena(root, project)
        output = _probe_unified_3p_arena(root)
    if output:
        print(output, flush=True)


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

    _validate_pinned_binary(root, compat_dir)

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
        "bridge": "libriichi3p.mjai.Bot",
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
    python = _runtime_python(root)
    patcher = project / "scripts" / "patch_mortal_unified_eval_stage5c.py"
    if not patcher.is_file():
        raise RuntimeError(f"unified Stage 5C evaluator patcher is missing: {patcher}")
    _run([str(python), str(patcher), "--root", str(root)], cwd=project)
    ensure_unified_3p_arena(root, project)


__all__ = [
    "AKAGI_PIN",
    "COMPAT_PROTOCOL",
    "LEGACY_3P_ACTION_SPACE",
    "LEGACY_3P_OBS_CHANNELS",
    "apply_runtime_evaluator",
    "checkpoint_obs_channels",
    "ensure_akagi_3p_compat",
    "ensure_unified_3p_arena",
]
