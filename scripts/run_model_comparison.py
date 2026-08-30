from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-.")
    return value or "comparison"


def _checkpoint(value: str, models_dir: Path) -> Path:
    raw = Path(value).expanduser()
    path = raw.resolve() if raw.is_absolute() else (models_dir / raw).resolve()
    if not path.is_file() or path.suffix.casefold() != ".pth":
        raise SystemExit(f"checkpoint does not exist or is not .pth: {path}")
    return path


def _run_checked(cmd: list[str], *, cwd: Path, env: dict[str, str], label: str) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout + "\n" + proc.stderr).splitlines()[-120:])
        raise RuntimeError(f"{label} failed with exit {proc.returncode}:\n{tail}")
    return proc


def _side_runtime_config(section: dict[str, object], control: dict[str, object], args) -> dict[str, object]:
    base = dict(section.get("challenger", {}))
    device = args.device or str(base.get("device", control.get("device", "cuda:0")))
    if args.compile is None:
        enable_compile = bool(base.get("enable_compile", control.get("enable_compile", False)))
    else:
        enable_compile = bool(args.compile)
    if args.amp is None:
        enable_amp = bool(base.get("enable_amp", control.get("enable_amp", True)))
    else:
        enable_amp = bool(args.amp)
    return {
        **base,
        "device": device,
        "enable_compile": enable_compile,
        "enable_amp": enable_amp,
        "enable_rule_based_agari_guard": bool(base.get("enable_rule_based_agari_guard", True)),
    }


def _eval_direction(
    *,
    runtime_python: Path,
    mortal_dir: Path,
    base_cfg: dict[str, object],
    mode: str,
    section_name: str,
    evaluator: str,
    players: int,
    challenger: Path,
    champion: Path,
    challenger_name: str,
    champion_name: str,
    seed_start: int,
    seed_count: int,
    seed_key: int,
    log_dir: Path,
    config_path: Path,
    common_side: dict[str, object],
    env: dict[str, str],
) -> dict[str, object]:
    import toml

    cfg = copy.deepcopy(base_cfg)
    control = cfg.setdefault("control", {})
    control["online"] = False
    section = cfg.setdefault(section_name, {})
    section["games_per_iter"] = players * seed_count
    section["iters"] = 1
    section["seed_start"] = seed_start
    section["seed_key"] = seed_key
    section["log_dir"] = str(log_dir)
    if mode == "4p":
        section.setdefault("akochan", {})["enabled"] = False

    for side_name, checkpoint, engine_name in (
        ("challenger", challenger, challenger_name),
        ("champion", champion, champion_name),
    ):
        side = section.setdefault(side_name, {})
        side.clear()
        side.update(common_side)
        side["state_file"] = str(checkpoint)
        side["name"] = engine_name

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(toml.dumps(cfg), encoding="utf-8")
    direction_env = dict(env)
    direction_env["MORTAL_CFG"] = str(config_path)
    direction_env["MORTAL_GAME_MODE"] = mode
    direction_env["MORTAL_PLAYER_COUNT"] = str(players)

    proc = _run_checked(
        [str(runtime_python), evaluator],
        cwd=mortal_dir,
        env=direction_env,
        label=f"{challenger_name} vs {champion_name}",
    )
    expected = players * seed_count
    logs = sorted(log_dir.glob("*.json.gz"))
    if len(logs) != expected:
        raise RuntimeError(f"{challenger_name} vs {champion_name}: expected {expected} logs, got {len(logs)}")
    return {
        "challenger": str(challenger),
        "champion": str(champion),
        "logs": len(logs),
        "log_dir": str(log_dir),
        "config": str(config_path),
        "stdout_tail": proc.stdout.strip().splitlines()[-5:],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run Mortal-docs-style bidirectional duplicate evaluation between two unified Mortal v4 checkpoints, "
            "then emit paired JSONL, strength tables, and optional rating-gate results."
        )
    )
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--mode", choices=("3p", "4p"), required=True)
    parser.add_argument("--candidate", required=True, help="Absolute path or runtime/<mode>/models relative path")
    parser.add_argument("--baseline", required=True, help="Absolute path or runtime/<mode>/models relative path")
    parser.add_argument("--candidate-name")
    parser.add_argument("--baseline-name")
    parser.add_argument("--seed-start", type=int, default=10000)
    parser.add_argument("--seed-count", type=int, default=100)
    parser.add_argument("--seed-key", type=lambda value: int(value, 0), default=0xD5DFAA4CEF265CD7)
    parser.add_argument("--device")
    parser.add_argument("--compile", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--amp", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--name")
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--round-kind", default="south")
    parser.add_argument("--room", default="*")
    parser.add_argument("--rank", default="*")
    parser.add_argument("--rank-points")
    parser.add_argument("--profile", help="Optional rating profile to evaluate with promotion_gate.py")
    parser.add_argument("--resamples", type=int, default=5000)
    parser.add_argument("--confidence", type=float, default=0.95)
    args = parser.parse_args()

    if args.seed_start < 0:
        raise SystemExit("--seed-start must be non-negative")
    if args.seed_count <= 0:
        raise SystemExit("--seed-count must be positive")

    root = args.runtime_root.expanduser().resolve()
    mortal_dir = root / "mortal"
    runtime_python = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    mode_root = root / "runtime" / args.mode
    models_dir = mode_root / "models"
    runs_dir = mode_root / "runs"
    base_config_path = mortal_dir / f"config.{args.mode}.toml"
    if not mortal_dir.is_dir() or not runtime_python.is_file() or not base_config_path.is_file():
        raise SystemExit(f"unified Mortal runtime is incomplete under {root}")

    candidate = _checkpoint(args.candidate, models_dir)
    baseline = _checkpoint(args.baseline, models_dir)
    if candidate == baseline:
        raise SystemExit("candidate and baseline must be different checkpoint paths")

    import toml

    base_cfg = toml.load(base_config_path)
    players = 3 if args.mode == "3p" else 4
    section_name = "1v2" if args.mode == "3p" else "1v3"
    evaluator = "one_vs_two.py" if args.mode == "3p" else "one_vs_three.py"
    section = dict(base_cfg.get(section_name, {}))
    common_side = _side_runtime_config(section, dict(base_cfg.get("control", {})), args)

    candidate_name = args.candidate_name or candidate.stem
    baseline_name = args.baseline_name or baseline.stem
    default_name = _slug(
        args.name
        or f"{candidate.stem}-vs-{baseline.stem}-seed-{args.seed_start}-n-{args.seed_count}"
    )
    output_root = (
        args.output_root.expanduser().resolve()
        if args.output_root is not None
        else runs_dir / "comparison" / default_name
    )
    if output_root.exists():
        if not args.fresh:
            raise SystemExit(f"comparison output already exists: {output_root}; use --fresh or another --name")
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    existing = os.environ.get("PYTHONPATH", "")
    parts = [str(PROJECT_ROOT), str(mortal_dir)]
    if existing:
        parts.append(existing)
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(parts)

    candidate_logs = output_root / "candidate-vs-baseline"
    baseline_logs = output_root / "baseline-vs-candidate"
    forward = _eval_direction(
        runtime_python=runtime_python,
        mortal_dir=mortal_dir,
        base_cfg=base_cfg,
        mode=args.mode,
        section_name=section_name,
        evaluator=evaluator,
        players=players,
        challenger=candidate,
        champion=baseline,
        challenger_name=candidate_name,
        champion_name=baseline_name,
        seed_start=args.seed_start,
        seed_count=args.seed_count,
        seed_key=args.seed_key,
        log_dir=candidate_logs,
        config_path=output_root / "candidate-vs-baseline.toml",
        common_side=common_side,
        env=env,
    )
    reverse = _eval_direction(
        runtime_python=runtime_python,
        mortal_dir=mortal_dir,
        base_cfg=base_cfg,
        mode=args.mode,
        section_name=section_name,
        evaluator=evaluator,
        players=players,
        challenger=baseline,
        champion=candidate,
        challenger_name=baseline_name,
        champion_name=candidate_name,
        seed_start=args.seed_start,
        seed_count=args.seed_count,
        seed_key=args.seed_key,
        log_dir=baseline_logs,
        config_path=output_root / "baseline-vs-candidate.toml",
        common_side=common_side,
        env=env,
    )

    paired_output = output_root / "paired.jsonl"
    builder_cmd = [
        str(runtime_python),
        str(PROJECT_ROOT / "scripts" / "build_paired_evaluation.py"),
        "--candidate-dir",
        str(candidate_logs),
        "--baseline-dir",
        str(baseline_logs),
        "--mode",
        args.mode,
        "--output",
        str(paired_output),
        "--candidate-name",
        candidate_name,
        "--baseline-name",
        baseline_name,
        "--round-kind",
        args.round_kind,
        "--room",
        args.room,
        "--rank",
        args.rank,
    ]
    if args.rank_points:
        builder_cmd.extend(["--rank-points", args.rank_points])
    _run_checked(builder_cmd, cwd=PROJECT_ROOT, env=env, label="paired strength builder")

    native_stat_output = output_root / "native-stat.json"
    _run_checked(
        [
            str(runtime_python),
            str(PROJECT_ROOT / "scripts" / "build_mortal_stat_report.py"),
            "--candidate-dir",
            str(candidate_logs),
            "--candidate-name",
            candidate_name,
            "--baseline-dir",
            str(baseline_logs),
            "--baseline-name",
            baseline_name,
            "--mode",
            args.mode,
            "--output",
            str(native_stat_output),
        ],
        cwd=PROJECT_ROOT,
        env=env,
        label="native Mortal Stat report",
    )
    native_stat = json.loads(native_stat_output.read_text(encoding="utf-8"))

    gate: dict[str, object] | None = None
    if args.profile:
        gate_output = output_root / "promotion-gate.json"
        gate_cmd = [
            str(runtime_python),
            str(PROJECT_ROOT / "scripts" / "promotion_gate.py"),
            "--input",
            str(paired_output),
            "--profile",
            args.profile,
            "--resamples",
            str(args.resamples),
            "--confidence",
            str(args.confidence),
            "--json-out",
            str(gate_output),
        ]
        gate_proc = subprocess.run(gate_cmd, cwd=PROJECT_ROOT, env=env, text=True, capture_output=True, check=False)
        if gate_proc.returncode not in (0, 10):
            tail = "\n".join((gate_proc.stdout + "\n" + gate_proc.stderr).splitlines()[-120:])
            raise RuntimeError(f"promotion gate execution failed with exit {gate_proc.returncode}:\n{tail}")
        gate = json.loads(gate_output.read_text(encoding="utf-8"))

    strength_path = paired_output.with_suffix(".summary.json")
    strength = json.loads(strength_path.read_text(encoding="utf-8"))
    manifest = {
        "protocol": "mortal-rogs-bidirectional-model-comparison-v1",
        "mode": args.mode,
        "players": players,
        "candidate": str(candidate),
        "baseline": str(baseline),
        "candidate_name": candidate_name,
        "baseline_name": baseline_name,
        "seed_start": args.seed_start,
        "seed_count": args.seed_count,
        "seed_key": args.seed_key,
        "contexts": players * args.seed_count,
        "forward": forward,
        "reverse": reverse,
        "paired_output": str(paired_output),
        "strength_summary": str(strength_path),
        "strength_markdown": str(paired_output.with_suffix(".summary.md")),
        "native_stat_report": str(native_stat_output),
        "native_stat_text": str(native_stat_output.with_suffix(".txt")),
        "candidate_minus_baseline": strength.get("candidate_minus_baseline"),
        "native_stat_candidate_minus_baseline": native_stat.get("candidate_minus_baseline"),
        "profile": args.profile,
        "promotion_gate": gate,
    }
    manifest_path = output_root / "comparison.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        "MORTAL_BIDIRECTIONAL_MODEL_COMPARISON_OK",
        f"mode={args.mode}",
        f"contexts={manifest['contexts']}",
        f"output={output_root}",
    )
    if gate is not None:
        print(
            "MORTAL_MODEL_COMPARISON_GATE",
            "PASS" if bool(gate.get("passed")) else "FAIL",
            f"profile={args.profile}",
        )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
