from __future__ import annotations

import argparse
import copy
import gzip
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.prepare_selfplay_population import POPULATION_PROTOCOL, normalize_mode, runtime_paths
from scripts.prepare_tenhou_training import configure, split_for, validate_data

GENERATION_PROTOCOL = "mortal-rogs-population-selfplay-data-v1"
GENERATION_STATE_PROTOCOL = "mortal-rogs-population-selfplay-state-v1"


def load_population(path: Path, mode: str) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("protocol") != POPULATION_PROTOCOL:
        raise ValueError(f"unsupported population manifest: {payload.get('protocol')!r}")
    if payload.get("mode") != mode:
        raise ValueError(f"population mode {payload.get('mode')!r} does not match {mode!r}")
    members = payload.get("members")
    if not isinstance(members, list) or not members:
        raise ValueError("population has no active members")
    return payload


def member_map(population: dict[str, object]) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for raw in population.get("members", []):
        if not isinstance(raw, dict):
            continue
        member_id = str(raw.get("id", ""))
        file_value = raw.get("file")
        if not member_id or not isinstance(file_value, str):
            continue
        path = Path(file_value).expanduser().resolve()
        if not path.is_file():
            raise ValueError(f"population member is missing: {path}")
        result[member_id] = raw
    if not result:
        raise ValueError("population has no usable member files")
    return result


def matchup_order(population: dict[str, object], members: dict[str, dict[str, object]]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    raw_order = population.get("matchup_order", [])
    if isinstance(raw_order, list):
        for raw in raw_order:
            if not isinstance(raw, dict):
                continue
            left = str(raw.get("challenger", ""))
            right = str(raw.get("champion", ""))
            if left in members and right in members and (left, right) not in result:
                result.append((left, right))
    if result:
        return result
    champion = str(population.get("champion_id", ""))
    ids = list(members)
    if len(ids) == 1:
        return [(ids[0], ids[0])]
    if champion not in members:
        champion = ids[0]
    for other in ids:
        if other == champion:
            continue
        result.extend([(other, champion), (champion, other)])
    result.append((champion, champion))
    return result


def _side_settings(base_cfg: dict[str, object], section_name: str, device: str, enable_compile: bool, enable_amp: bool) -> dict[str, object]:
    section = dict(base_cfg.get(section_name, {}))
    source = dict(section.get("challenger", {}))
    control = dict(base_cfg.get("control", {}))
    return {
        **source,
        "device": device or str(source.get("device", control.get("device", "cuda:0"))),
        "enable_compile": enable_compile,
        "enable_amp": enable_amp,
        "enable_rule_based_agari_guard": bool(source.get("enable_rule_based_agari_guard", True)),
    }


def _run_matchup(
    *,
    runtime_root: Path,
    mode: str,
    challenger: dict[str, object],
    champion: dict[str, object],
    seed_start: int,
    seed_count: int,
    seed_key: int,
    device: str,
    enable_compile: bool,
    enable_amp: bool,
    output_dir: Path,
) -> list[Path]:
    import toml

    paths = runtime_paths(runtime_root, mode)
    base_cfg = toml.load(paths["config"])
    players = 3 if mode == "3p" else 4
    section_name = "1v2" if mode == "3p" else "1v3"
    evaluator = "one_vs_two.py" if mode == "3p" else "one_vs_three.py"
    side_settings = _side_settings(base_cfg, section_name, device, enable_compile, enable_amp)

    cfg = copy.deepcopy(base_cfg)
    cfg.setdefault("control", {})["online"] = False
    section = cfg.setdefault(section_name, {})
    section["games_per_iter"] = players * seed_count
    section["iters"] = 1
    section["seed_start"] = seed_start
    section["seed_key"] = seed_key
    section["log_dir"] = str(output_dir)
    if mode == "4p":
        section.setdefault("akochan", {})["enabled"] = False

    for side_name, member in (("challenger", challenger), ("champion", champion)):
        side = section.setdefault(side_name, {})
        side.clear()
        side.update(side_settings)
        side["state_file"] = str(Path(str(member["file"])).resolve())
        side["name"] = f"population-{member['id']}"

    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=f".{mode}.toml", encoding="utf-8", delete=False) as temp_cfg:
        temp_path = Path(temp_cfg.name)
        temp_cfg.write(toml.dumps(cfg))
    try:
        env = os.environ.copy()
        existing = env.get("PYTHONPATH", "")
        parts = [str(PROJECT_ROOT), str(paths["mortal"])]
        if existing:
            parts.append(existing)
        env["PYTHONPATH"] = os.pathsep.join(parts)
        env["MORTAL_CFG"] = str(temp_path)
        env["MORTAL_GAME_MODE"] = mode
        env["MORTAL_PLAYER_COUNT"] = str(players)
        cmd = [str(paths["python"]), evaluator]
        print(
            "MORTAL_POPULATION_MATCHUP",
            f"mode={mode}",
            f"challenger={challenger['id']}",
            f"champion={champion['id']}",
            f"seed_start={seed_start}",
            f"contexts={seed_count}",
            flush=True,
        )
        proc = subprocess.run(cmd, cwd=paths["mortal"], env=env, text=True, capture_output=True, check=False)
        if proc.returncode != 0:
            tail = "\n".join((proc.stdout + "\n" + proc.stderr).splitlines()[-120:])
            raise RuntimeError(f"population evaluator failed with exit {proc.returncode}:\n{tail}")
    finally:
        temp_path.unlink(missing_ok=True)

    logs = sorted(output_dir.glob("*.json.gz"))
    expected = players * seed_count
    if len(logs) != expected:
        raise RuntimeError(f"expected {expected} self-play logs, got {len(logs)} in {output_dir}")
    return logs


def _validate_header(path: Path, players: int) -> None:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        first = json.loads(f.readline())
    if first.get("type") != "start_game" or len(first.get("names", [])) != players:
        raise RuntimeError(f"invalid generated MJAI header: {path}")


def _state_path(run_root: Path, mode: str) -> Path:
    return run_root / f"state-{mode}.json"


def load_generation_state(run_root: Path, mode: str, requested_seed_start: int) -> dict[str, int | str]:
    path = _state_path(run_root, mode)
    if not path.is_file():
        return {
            "protocol": GENERATION_STATE_PROTOCOL,
            "mode": mode,
            "next_seed": requested_seed_start,
            "next_batch": 0,
            "games_committed": 0,
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("protocol") != GENERATION_STATE_PROTOCOL or payload.get("mode") != mode:
        raise RuntimeError(f"invalid self-play generation state: {path}")
    next_seed = int(payload.get("next_seed", requested_seed_start))
    next_batch = int(payload.get("next_batch", 0))
    games_committed = int(payload.get("games_committed", 0))
    if next_seed < 0 or next_batch < 0 or games_committed < 0:
        raise RuntimeError(f"negative values in self-play generation state: {path}")
    return {
        "protocol": GENERATION_STATE_PROTOCOL,
        "mode": mode,
        "next_seed": max(requested_seed_start, next_seed),
        "next_batch": next_batch,
        "games_committed": games_committed,
    }


def save_generation_state(run_root: Path, state: dict[str, int | str]) -> Path:
    path = _state_path(run_root, str(state["mode"]))
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def stage_logs(
    logs: list[Path],
    data_root: Path,
    *,
    batch_index: int,
    seed_start: int,
    val_ratio: float,
    players: int,
) -> tuple[int, int, int]:
    train_count = 0
    val_count = 0
    reused = 0
    for index, source in enumerate(logs):
        logical_name = f"selfplay-s{seed_start:012d}-b{batch_index:06d}-g{index:04d}-{source.name}"
        split = split_for(logical_name, val_ratio)
        destination = data_root / split / logical_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        _validate_header(source, players)
        if destination.exists():
            _validate_header(destination, players)
            source.unlink(missing_ok=True)
            reused += 1
            continue
        shutil.move(str(source), str(destination))
        if split == "train":
            train_count += 1
        else:
            val_count += 1
    return train_count, val_count, reused


def ensure_validation_split(data_root: Path) -> None:
    train = sorted((data_root / "train").glob("*.json.gz"))
    val = sorted((data_root / "val").glob("*.json.gz"))
    if val or len(train) < 2:
        return
    fallback = train[-1]
    target = data_root / "val" / fallback.name
    target.parent.mkdir(parents=True, exist_ok=True)
    fallback.replace(target)
    print(f"MORTAL_SELFPLAY_VAL_FALLBACK file={target.name}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate Mortal-native MJAI training logs by running the validated checkpoint population through "
            "the existing unified 3P/4P evaluator. No external human-log service is required."
        )
    )
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--mode", choices=("3p", "4p"), required=True)
    parser.add_argument("--population", type=Path)
    parser.add_argument("--games", type=int, default=1000, help="Minimum number of new/recovered game logs to commit this invocation")
    parser.add_argument("--contexts-per-matchup", type=int, default=32)
    parser.add_argument("--seed-start", type=int, default=1_000_000, help="Lower bound for the resumable seed cursor")
    parser.add_argument("--seed-key", type=lambda value: int(value, 0), default=0xD5DFAA4CEF265CD7)
    parser.add_argument("--val-ratio", type=float, default=0.05)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--compile", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--amp", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--activate", action="store_true", help="Point Mortal + GRP dataset config at the generated data root")
    parser.add_argument("--validate-samples", type=int, default=16)
    args = parser.parse_args()

    if args.games <= 0 or args.contexts_per_matchup <= 0 or args.seed_start < 0:
        raise SystemExit("games and contexts-per-matchup must be positive; seed-start must be non-negative")
    if not 0 < args.val_ratio < 0.5:
        raise SystemExit("val-ratio must be in (0, 0.5)")

    mode = normalize_mode(args.mode)
    paths = runtime_paths(args.runtime_root, mode)
    population_path = (
        args.population.expanduser().resolve()
        if args.population is not None
        else paths["population"] / "population.json"
    )
    if not population_path.is_file():
        raise SystemExit(f"population manifest does not exist: {population_path}")

    population = load_population(population_path, mode)
    members = member_map(population)
    order = matchup_order(population, members)
    if not order:
        raise SystemExit("population produced no matchups")

    players = 3 if mode == "3p" else 4
    data_root = paths["mode_root"] / "data" / "selfplay-population"
    run_root = paths["runs"] / "selfplay-data"
    run_root.mkdir(parents=True, exist_ok=True)
    state = load_generation_state(run_root, mode, args.seed_start)
    seed_cursor = int(state["next_seed"])
    batch_index = int(state["next_batch"])
    first_seed = seed_cursor
    first_batch = batch_index
    generated = 0
    train_added = 0
    val_added = 0
    reused_total = 0
    batches: list[dict[str, object]] = []

    print(
        "MORTAL_SELFPLAY_RESUME",
        f"mode={mode}",
        f"seed={seed_cursor}",
        f"batch={batch_index}",
        f"games_committed={state['games_committed']}",
        flush=True,
    )

    while generated < args.games:
        left_id, right_id = order[batch_index % len(order)]
        remaining_games = args.games - generated
        contexts_needed = max(1, math.ceil(remaining_games / players))
        contexts = min(args.contexts_per_matchup, contexts_needed)
        batch_seed = seed_cursor
        raw_dir = run_root / f"raw-{batch_seed}-{batch_index:06d}"
        if raw_dir.exists():
            shutil.rmtree(raw_dir)
        logs = _run_matchup(
            runtime_root=paths["root"],
            mode=mode,
            challenger=members[left_id],
            champion=members[right_id],
            seed_start=batch_seed,
            seed_count=contexts,
            seed_key=args.seed_key,
            device=args.device,
            enable_compile=bool(args.compile),
            enable_amp=bool(args.amp),
            output_dir=raw_dir,
        )
        train_count, val_count, reused = stage_logs(
            logs,
            data_root,
            batch_index=batch_index,
            seed_start=batch_seed,
            val_ratio=args.val_ratio,
            players=players,
        )
        shutil.rmtree(raw_dir, ignore_errors=True)
        batch_games = train_count + val_count + reused
        generated += batch_games
        train_added += train_count
        val_added += val_count
        reused_total += reused
        batches.append(
            {
                "batch": batch_index,
                "challenger": left_id,
                "champion": right_id,
                "seed_start": batch_seed,
                "contexts": contexts,
                "games": batch_games,
                "train_added": train_count,
                "val_added": val_count,
                "reused_after_interruption": reused,
            }
        )
        seed_cursor += contexts
        batch_index += 1
        state["next_seed"] = seed_cursor
        state["next_batch"] = batch_index
        state["games_committed"] = int(state["games_committed"]) + batch_games
        state_path = save_generation_state(run_root, state)
        print(
            "MORTAL_SELFPLAY_DATA_PROGRESS",
            f"mode={mode}",
            f"generated={generated}/{args.games}",
            f"train_added={train_added}",
            f"val_added={val_added}",
            f"reused={reused_total}",
            f"next_seed={seed_cursor}",
            f"state={state_path}",
            flush=True,
        )

    ensure_validation_split(data_root)
    train_total, val_total = validate_data(paths["root"], mode, data_root, args.validate_samples)
    config_path = configure(paths["root"], mode, data_root) if args.activate else paths["config"]

    manifest = {
        "protocol": GENERATION_PROTOCOL,
        "mode": mode,
        "players": players,
        "population": str(population_path),
        "champion_id": population.get("champion_id"),
        "requested_games": args.games,
        "committed_this_run": generated,
        "train_added": train_added,
        "val_added": val_added,
        "reused_after_interruption": reused_total,
        "train_total": train_total,
        "val_total": val_total,
        "data_root": str(data_root),
        "config": str(config_path),
        "activated": bool(args.activate),
        "requested_seed_start": args.seed_start,
        "seed_start": first_seed,
        "seed_end": seed_cursor,
        "batch_start": first_batch,
        "batch_end": batch_index,
        "seed_key": args.seed_key,
        "device": args.device,
        "compile": bool(args.compile),
        "amp": bool(args.amp),
        "state": str(_state_path(run_root, mode)),
        "batches": batches,
    }
    manifest_path = run_root / f"generation-{mode}-s{first_seed}-b{first_batch:06d}.json"
    tmp = manifest_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(manifest_path)
    print(
        "MORTAL_POPULATION_SELFPLAY_DATA_READY",
        f"mode={mode}",
        f"committed={generated}",
        f"train={train_total}",
        f"val={val_total}",
        f"activated={bool(args.activate)}",
        f"manifest={manifest_path}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
