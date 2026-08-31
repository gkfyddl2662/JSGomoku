from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

POPULATION_PROTOCOL = "mortal-rogs-selfplay-population-v1"


def normalize_mode(value: str) -> str:
    mode = value.strip().casefold()
    aliases = {"3": "3p", "3p": "3p", "sanma": "3p", "4": "4p", "4p": "4p", "yonma": "4p"}
    if mode not in aliases:
        raise ValueError(f"unsupported mode: {value!r}")
    return aliases[mode]


def checkpoint_sha256(path: Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def safe_stem(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-.")
    return cleaned or "checkpoint"


def resolve_checkpoint(value: str | Path) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file() or path.suffix.casefold() != ".pth":
        raise ValueError(f"checkpoint must be an existing .pth file: {path}")
    return path


def runtime_paths(runtime_root: Path, mode: str) -> dict[str, Path]:
    root = runtime_root.expanduser().resolve()
    normalized = normalize_mode(mode)
    py = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    mortal = root / "mortal"
    config = mortal / f"config.{normalized}.toml"
    mode_root = root / "runtime" / normalized
    models = mode_root / "models"
    runs = mode_root / "runs"
    if not py.is_file() or not mortal.is_dir() or not config.is_file():
        raise ValueError(f"unified Mortal runtime is incomplete under {root}")
    return {
        "root": root,
        "python": py,
        "mortal": mortal,
        "config": config,
        "mode_root": mode_root,
        "models": models,
        "runs": runs,
        "population": models / "population",
    }


def _run_checked(cmd: list[str], *, cwd: Path, env: dict[str, str], label: str) -> dict[str, object]:
    started = time.monotonic()
    proc = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    elapsed = time.monotonic() - started
    tail = (proc.stdout + "\n" + proc.stderr).strip().splitlines()[-40:]
    if proc.returncode != 0:
        raise RuntimeError(f"{label} failed with exit {proc.returncode}:\n" + "\n".join(tail))
    return {"seconds": round(elapsed, 3), "tail": tail[-8:]}


def validate_checkpoint(
    *,
    runtime_root: Path,
    mode: str,
    checkpoint: Path,
    device: str,
    gameplay_smoke: bool,
    smoke_seed: int,
) -> dict[str, object]:
    paths = runtime_paths(runtime_root, mode)
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    parts = [str(PROJECT_ROOT), str(paths["mortal"])]
    if existing:
        parts.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    env["MORTAL_CFG"] = str(paths["config"])
    env["MORTAL_GAME_MODE"] = mode
    env["MORTAL_PLAYER_COUNT"] = "3" if mode == "3p" else "4"

    abi_cmd = [
        str(paths["python"]),
        str(PROJECT_ROOT / "scripts" / "check_mortal_api_checkpoint.py"),
        "--runtime-root",
        str(paths["root"]),
        "--model",
        str(checkpoint),
        "--mode",
        mode,
        "--device",
        device,
    ]
    abi = _run_checked(abi_cmd, cwd=PROJECT_ROOT, env=env, label=f"{mode} ABI/forward probe")

    result: dict[str, object] = {"abi_forward": abi, "gameplay": None}
    if not gameplay_smoke:
        return result

    with tempfile.TemporaryDirectory(prefix=f"mortal-rogs-{mode}-checkpoint-smoke-") as td:
        temp = Path(td)
        shadow = temp / f"{checkpoint.stem}.shadow.pth"
        try:
            os.link(checkpoint, shadow)
        except OSError:
            shutil.copy2(checkpoint, shadow)
        out = temp / "comparison"
        cmd = [
            str(paths["python"]),
            str(PROJECT_ROOT / "scripts" / "run_model_comparison.py"),
            "--runtime-root",
            str(paths["root"]),
            "--mode",
            mode,
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
            str(out),
            "--device",
            device,
            "--no-compile",
            "--fresh",
        ]
        if device.casefold().startswith("cpu"):
            cmd.append("--no-amp")
        else:
            cmd.append("--amp")
        result["gameplay"] = _run_checked(cmd, cwd=PROJECT_ROOT, env=env, label=f"{mode} gameplay smoke")
    return result


def choose_champion(
    accepted: list[dict[str, object]], explicit: Path | None = None
) -> dict[str, object]:
    if not accepted:
        raise ValueError("no accepted checkpoints")
    if explicit is not None:
        explicit_resolved = str(explicit.resolve())
        for item in accepted:
            if item["source"] == explicit_resolved:
                return item
        raise ValueError(f"explicit champion was not accepted: {explicit}")
    trusted = [item for item in accepted if bool(item.get("trusted"))]
    return trusted[0] if trusted else accepted[0]


def build_matchup_order(member_ids: list[str], champion_id: str) -> list[tuple[str, str]]:
    ids = list(dict.fromkeys(member_ids))
    if not ids:
        return []
    if len(ids) == 1:
        return [(ids[0], ids[0])]

    ordered: list[tuple[str, str]] = []
    others = [value for value in ids if value != champion_id]
    for other in others:
        ordered.append((other, champion_id))
        ordered.append((champion_id, other))
    for left in ids:
        for right in ids:
            if left != right and (left, right) not in ordered:
                ordered.append((left, right))
    ordered.append((champion_id, champion_id))
    return ordered


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate external Mortal v4 checkpoints and build a mode-isolated self-play population. "
            "Rejected or wrong-ABI checkpoints are never copied into the active pool."
        )
    )
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--mode", choices=("3p", "4p"), required=True)
    parser.add_argument("--candidate", action="append", default=[], help="External .pth path; repeat for multiple models")
    parser.add_argument("--candidate-dir", type=Path, help="Optional directory recursively scanned for *.pth")
    parser.add_argument("--champion", type=Path, help="Preferred champion path; it must pass validation")
    parser.add_argument("--trusted", action="append", default=[], help="Known-good .pth path; repeat as needed")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--gameplay-smoke", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--smoke-seed", type=int, default=910000)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()

    mode = normalize_mode(args.mode)
    paths = runtime_paths(args.runtime_root, mode)
    candidates: list[Path] = []
    for value in args.candidate:
        candidates.append(resolve_checkpoint(value))
    if args.candidate_dir is not None:
        root = args.candidate_dir.expanduser().resolve()
        if not root.is_dir():
            raise SystemExit(f"candidate directory does not exist: {root}")
        candidates.extend(sorted(path.resolve() for path in root.rglob("*.pth") if path.is_file()))
    if not candidates:
        raise SystemExit("provide at least one --candidate or --candidate-dir")

    deduped: list[Path] = []
    seen_paths: set[str] = set()
    for path in candidates:
        key = str(path).casefold() if os.name == "nt" else str(path)
        if key not in seen_paths:
            seen_paths.add(key)
            deduped.append(path)

    trusted_paths = {str(resolve_checkpoint(value)) for value in args.trusted}
    explicit_champion = resolve_checkpoint(args.champion) if args.champion is not None else None

    population_dir = paths["population"]
    population_dir.mkdir(parents=True, exist_ok=True)
    accepted: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    seen_hashes: dict[str, dict[str, object]] = {}

    for index, source in enumerate(deduped):
        print(f"MORTAL_POPULATION_PROBE mode={mode} file={source.name}", flush=True)
        try:
            sha = checkpoint_sha256(source)
            if sha in seen_hashes:
                duplicate = dict(seen_hashes[sha])
                aliases = list(duplicate.get("aliases", []))
                aliases.append(str(source))
                duplicate["aliases"] = aliases
                seen_hashes[sha].update(duplicate)
                continue

            validation = validate_checkpoint(
                runtime_root=paths["root"],
                mode=mode,
                checkpoint=source,
                device=args.device,
                gameplay_smoke=args.gameplay_smoke,
                smoke_seed=args.smoke_seed + index,
            )
            member_id = sha[:16]
            target_name = f"member-{member_id}-{safe_stem(source.stem)}.pth"
            target = population_dir / target_name
            if not target.is_file() or checkpoint_sha256(target) != sha:
                tmp = target.with_suffix(".pth.tmp")
                shutil.copy2(source, tmp)
                tmp.replace(target)
            item: dict[str, object] = {
                "id": member_id,
                "mode": mode,
                "source": str(source),
                "file": str(target),
                "relative": str(target.relative_to(paths["models"])),
                "sha256": sha,
                "bytes": source.stat().st_size,
                "trusted": str(source) in trusted_paths,
                "validation": validation,
                "aliases": [],
            }
            accepted.append(item)
            seen_hashes[sha] = item
            print(f"MORTAL_POPULATION_ACCEPT mode={mode} id={member_id} file={source.name}", flush=True)
        except Exception as exc:
            rejected.append({"mode": mode, "source": str(source), "error": f"{type(exc).__name__}: {exc}"})
            print(f"MORTAL_POPULATION_REJECT mode={mode} file={source.name} reason={type(exc).__name__}", flush=True)

    if not accepted:
        manifest_path = args.manifest.expanduser().resolve() if args.manifest else population_dir / "population.json"
        manifest_path.write_text(
            json.dumps({"protocol": POPULATION_PROTOCOL, "mode": mode, "accepted": [], "rejected": rejected}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        raise SystemExit(f"no {mode} checkpoint passed validation; manifest={manifest_path}")

    try:
        champion = choose_champion(accepted, explicit_champion)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    champion_id = str(champion["id"])
    for item in accepted:
        item["role"] = "champion" if item["id"] == champion_id else "opponent"

    matchup_order = build_matchup_order([str(item["id"]) for item in accepted], champion_id)
    manifest = {
        "protocol": POPULATION_PROTOCOL,
        "mode": mode,
        "players": 3 if mode == "3p" else 4,
        "device": args.device,
        "gameplay_smoke": bool(args.gameplay_smoke),
        "champion_id": champion_id,
        "champion": champion["relative"],
        "members": accepted,
        "rejected": rejected,
        "matchup_order": [{"challenger": left, "champion": right} for left, right in matchup_order],
        "notes": {
            "single_member": len(accepted) == 1,
            "single_member_policy": "mirror self-play until learner/checkpoint snapshots expand the pool",
            "promotion": "new learners are challengers; duplicate evaluation must pass before champion replacement",
        },
    }
    manifest_path = args.manifest.expanduser().resolve() if args.manifest else population_dir / "population.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_manifest = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    tmp_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_manifest.replace(manifest_path)

    print(
        "MORTAL_SELFPLAY_POPULATION_READY",
        f"mode={mode}",
        f"accepted={len(accepted)}",
        f"rejected={len(rejected)}",
        f"champion={champion_id}",
        f"manifest={manifest_path}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
