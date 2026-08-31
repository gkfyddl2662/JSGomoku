from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOUOU_REPO = "https://github.com/Apricot-S/houou-logs.git"
HOUOU_SHA = "d4ca693771517b67172521f2bd76517500db4a6e"
SANMA_REPO = "https://github.com/Mateces/tenhou-sanma-to-mjai.git"
SANMA_SHA = "e0bd7bffe24227f97600c710cffa4490117b634a"
YONMA_REPO = "https://github.com/Jim137/mjlog2mjai.git"
YONMA_SHA = "c133f7dbf61046feaf1af72369d9a44056807657"


def run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    print("+", subprocess.list2cmdline([str(x) for x in cmd]), flush=True)
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def checkout(path: Path, repo: str, sha: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not (path / ".git").is_dir():
        if path.exists():
            shutil.rmtree(path)
        run(["git", "clone", "--filter=blob:none", repo, str(path)])
    head = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    if head != sha:
        run(["git", "-C", str(path), "fetch", "--depth", "1", "origin", sha])
        run(["git", "-C", str(path), "checkout", "--detach", sha])
    return path


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import converter: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def split_for(name: str, ratio: float) -> str:
    bucket = int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], "big") % 1_000_000
    return "val" if bucket < int(ratio * 1_000_000) else "train"


def install_tools(py: Path, tools: Path) -> tuple[Path, Path]:
    houou = checkout(tools / "houou-logs", HOUOU_REPO, HOUOU_SHA)
    marker = tools / f".houou-{HOUOU_SHA}"
    if not marker.is_file():
        run([str(py), "-m", "pip", "install", "--upgrade", str(houou)])
        marker.write_text(HOUOU_SHA + "\n", encoding="utf-8")
    sanma = checkout(tools / "tenhou-sanma-to-mjai", SANMA_REPO, SANMA_SHA)
    yonma = checkout(tools / "mjlog2mjai", YONMA_REPO, YONMA_SHA)
    return sanma, yonma


def download_xml(py: Path, cache: Path, modes: list[str], limits: dict[str, int]) -> dict[str, Path]:
    db = cache / "houou-current.db"
    cache.mkdir(parents=True, exist_ok=True)
    # Sequential by design: Tenhou permits one download session at a time.
    run([str(py), "-m", "houou_logs", "fetch", str(db), "--archive"])
    run([str(py), "-m", "houou_logs", "fetch", str(db)])
    result: dict[str, Path] = {}
    for mode in modes:
        players = "3" if mode == "3p" else "4"
        target = limits[mode]
        out = cache / "xml" / mode
        out.mkdir(parents=True, exist_ok=True)
        existing = len(list(out.glob("*.xml")))
        if existing < target:
            remaining = target - existing
            run([str(py), "-m", "houou_logs", "download", str(db), "--players", players, "--limit", str(remaining)])
            run([str(py), "-m", "houou_logs", "validate", str(db)])
            run([str(py), "-m", "houou_logs", "export", str(db), str(out), "--players", players, "--limit", str(target)])
        print(f"TENHOU_XML_READY mode={mode} files={len(list(out.glob('*.xml')))} target={target}")
        result[mode] = out
    return result


def convert(mode: str, xml_dir: Path, data_dir: Path, sanma_dir: Path, yonma_dir: Path, ratio: float) -> dict:
    failures: list[str] = []
    done = reused = 0
    if mode == "3p":
        x2j = load_module("mortal_rogs_x2j", sanma_dir / "xml_to_tenhou6.py")
        t2m = load_module("mortal_rogs_t2m", sanma_dir / "tenhou6_to_mjai.py")
    else:
        y2m = load_module("mortal_rogs_y2m", yonma_dir / "parse.py")

    files = sorted(xml_dir.glob("*.xml"))
    if not files:
        raise RuntimeError(f"no downloaded XML for {mode}: {xml_dir}")

    for source in files:
        split = split_for(source.name, ratio)
        target = data_dir / split / f"{source.stem}.json.gz"
        if target.is_file() and target.stat().st_size > 32:
            reused += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        try:
            if mode == "3p":
                raw = x2j.convert_xml_to_tenhou6(source.read_text(encoding="utf-8"))
                events = t2m.convert_tenhou6_json(raw)
                with gzip.open(tmp, "wt", encoding="utf-8", newline="\n") as f:
                    for event in events:
                        f.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
            else:
                text = y2m.parse_mjlog_to_mjai(y2m.load_mjlog(str(source)))
                with gzip.open(tmp, "wt", encoding="utf-8", newline="\n") as f:
                    f.write(text.rstrip("\n") + "\n")
            tmp.replace(target)
            done += 1
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            failures.append(f"{source.name}: {type(exc).__name__}: {exc}")

    total = done + reused + len(failures)
    if failures:
        (data_dir / "conversion-errors.txt").write_text("\n".join(failures) + "\n", encoding="utf-8")
    if total == 0 or len(failures) / total > 0.05:
        raise RuntimeError(f"{mode} conversion failure rate too high: {len(failures)}/{total}")
    return {"converted": done, "reused": reused, "failed": len(failures)}


def validate_data(runtime: Path, mode: str, data: Path, samples: int) -> tuple[int, int]:
    train = sorted((data / "train").glob("*.json.gz"))
    val = sorted((data / "val").glob("*.json.gz"))
    if not train or not val:
        raise RuntimeError(f"{mode} needs non-empty train/val splits: train={len(train)} val={len(val)}")
    expected = 3 if mode == "3p" else 4
    for path in (train + val)[:samples]:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            first = json.loads(f.readline())
        if first.get("type") != "start_game" or len(first.get("names", [])) != expected:
            raise RuntimeError(f"{mode} invalid MJAI header: {path}")

    mortal = runtime / "mortal"
    sys.path.insert(0, str(mortal))
    old = os.environ.get("MORTAL_CFG")
    os.environ["MORTAL_CFG"] = str(mortal / f"config.{mode}.toml")
    try:
        import libriichi  # type: ignore
        probe = (train + val)[: min(samples, len(train) + len(val))]
        loaded = libriichi.dataset.GameplayLoader(
            version=4, oracle=False, player_names=None, excludes=None, augmented=False
        ).load_gz_log_files([str(p) for p in probe])
        if not loaded:
            raise RuntimeError(f"{mode} libriichi rejected prepared MJAI logs")
    finally:
        if old is None:
            os.environ.pop("MORTAL_CFG", None)
        else:
            os.environ["MORTAL_CFG"] = old
        sys.path.remove(str(mortal))
    return len(train), len(val)


def configure(runtime: Path, mode: str, data: Path) -> Path:
    import toml
    config = runtime / "mortal" / f"config.{mode}.toml"
    cfg = toml.load(config)
    root = runtime / "runtime" / mode
    models = root / "models"
    runs = root / "runs"
    models.mkdir(parents=True, exist_ok=True)
    train_glob = str(data / "train" / "**" / "*.json.gz")
    val_glob = str(data / "val" / "**" / "*.json.gz")

    ds = cfg.setdefault("dataset", {})
    ds["globs"] = [train_glob]
    ds["file_index"] = str(root / "data" / "file-index.pth")
    grp = cfg.setdefault("grp", {})
    grp["state_file"] = str(models / "grp.pth")
    grp.setdefault("control", {})["tensorboard_dir"] = str(runs / "grp" / "tensorboard")
    gds = grp.setdefault("dataset", {})
    gds["train_globs"] = [train_glob]
    gds["val_globs"] = [val_glob]
    gds["file_index"] = str(root / "data" / "grp-file-index.pth")
    baseline = str(models / "baseline.pth")
    for side in ("train", "test"):
        cfg.setdefault("baseline", {}).setdefault(side, {})["state_file"] = baseline

    tmp = config.with_suffix(".toml.prepare.tmp")
    tmp.write_text(toml.dumps(cfg), encoding="utf-8")
    tmp.replace(config)
    Path(ds["file_index"]).unlink(missing_ok=True)
    Path(gds["file_index"]).unlink(missing_ok=True)
    return config


def check_checkpoint(py: Path, runtime: Path, mode: str, path: Path) -> None:
    run([
        str(py), str(PROJECT_ROOT / "scripts" / "check_mortal_api_checkpoint.py"),
        "--runtime-root", str(runtime), "--model", str(path), "--mode", mode, "--device", "cpu",
    ], cwd=PROJECT_ROOT)


def prepare_baseline(py: Path, runtime: Path, mode: str, requested: Path | None) -> dict:
    models = runtime / "runtime" / mode / "models"
    models.mkdir(parents=True, exist_ok=True)
    dst = models / "baseline.pth"
    if requested:
        src = requested.expanduser().resolve()
        kind = "user"
    else:
        src = runtime / "runtime" / "smoke-training" / f"smoke-trained-{mode}.pth"
        kind = "validated-smoke-reference"
    if not src.is_file():
        raise RuntimeError(f"{mode} baseline source missing: {src}")
    check_checkpoint(py, runtime, mode, src)
    if src.resolve() != dst.resolve():
        shutil.copy2(src, dst)
    check_checkpoint(py, runtime, mode, dst)
    return {"source": str(src), "destination": str(dst), "kind": kind}


def train_grp(py: Path, runtime: Path, mode: str, config: Path, target: int, retrain: bool) -> dict:
    import toml
    import torch
    state = runtime / "runtime" / mode / "models" / "grp.pth"
    if retrain:
        state.unlink(missing_ok=True)
    if state.is_file():
        saved = torch.load(state, weights_only=True, map_location="cpu")
        players = 3 if mode == "3p" else 4
        if int(saved.get("num_players", players)) != players:
            raise RuntimeError(f"{mode} existing GRP belongs to another mode")
        saved_steps = int(saved.get("steps", 0))
        if not retrain and saved_steps >= target:
            return {"checkpoint": str(state), "steps": saved_steps, "trained": False}

    cfg = toml.load(config)
    cfg["grp"]["control"]["save_every"] = min(int(cfg["grp"]["control"].get("save_every", 2000)), target)
    cfg["grp"]["control"]["val_steps"] = min(int(cfg["grp"]["control"].get("val_steps", 400)), 100)
    config.write_text(toml.dumps(cfg), encoding="utf-8")
    env = os.environ.copy()
    env.update({
        "MORTAL_CFG": str(config),
        "MORTAL_GAME_MODE": mode,
        "MORTAL_PLAYER_COUNT": "3" if mode == "3p" else "4",
        "PYTHONPATH": os.pathsep.join([str(PROJECT_ROOT), str(runtime / "mortal"), env.get("PYTHONPATH", "")]).rstrip(os.pathsep),
    })
    command = [str(py), str(runtime / "mortal" / "train_grp.py")]
    print("+", subprocess.list2cmdline(command), flush=True)
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    proc = subprocess.Popen(command, cwd=runtime / "mortal", env=env, creationflags=flags)
    try:
        while True:
            if state.is_file():
                try:
                    saved = torch.load(state, weights_only=True, map_location="cpu")
                    steps = int(saved.get("steps", 0))
                    print(f"GRP_PROGRESS mode={mode} steps={steps}/{target}", flush=True)
                    if steps >= target:
                        if os.name == "nt":
                            proc.send_signal(signal.CTRL_BREAK_EVENT)
                        else:
                            proc.send_signal(signal.SIGINT)
                        break
                except (OSError, EOFError, RuntimeError):
                    pass
            code = proc.poll()
            if code is not None:
                if code != 0:
                    raise RuntimeError(f"{mode} train_grp.py exited with code {code}")
                break
            time.sleep(2)
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.terminate()

    if not state.is_file():
        raise RuntimeError(f"{mode} GRP training produced no checkpoint")
    saved = torch.load(state, weights_only=True, map_location="cpu")
    players = 3 if mode == "3p" else 4
    if int(saved.get("num_players", players)) != players or int(saved.get("steps", 0)) < target:
        raise RuntimeError(f"{mode} GRP checkpoint failed mode/step validation")
    return {"checkpoint": str(state), "steps": int(saved["steps"]), "trained": True}


def main() -> int:
    p = argparse.ArgumentParser(description="One-shot Tenhou Houou data/baseline/GRP preparation.")
    p.add_argument("--runtime-root", type=Path, required=True)
    p.add_argument("--modes", choices=("both", "3p", "4p"), default="both")
    p.add_argument("--limit-3p", type=int, default=5000)
    p.add_argument("--limit-4p", type=int, default=5000)
    p.add_argument("--grp-steps", type=int, default=10000)
    p.add_argument("--val-ratio", type=float, default=0.05)
    p.add_argument("--baseline-3p", type=Path)
    p.add_argument("--baseline-4p", type=Path)
    p.add_argument("--retrain-grp", action="store_true")
    p.add_argument("--accept-tenhou-log-terms", action="store_true")
    p.add_argument("--manifest", type=Path)
    args = p.parse_args()
    if not args.accept_tenhou_log_terms:
        raise SystemExit("Pass --accept-tenhou-log-terms: keep logs local, do not redistribute, and use one download session.")
    if min(args.limit_3p, args.limit_4p, args.grp_steps) <= 0 or not 0 < args.val_ratio < 0.5:
        raise SystemExit("limits/GRP steps must be positive and val-ratio must be in (0, 0.5)")

    runtime = args.runtime_root.expanduser().resolve()
    py = runtime / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not py.is_file():
        raise SystemExit(f"runtime Python missing: {py}")
    modes = ["3p", "4p"] if args.modes == "both" else [args.modes]
    limits = {"3p": args.limit_3p, "4p": args.limit_4p}
    tools = runtime / "runtime" / "tools" / "tenhou-prep"
    cache = runtime / "runtime" / "tenhou-cache"

    print("TENHOU_LOCAL_DATA_NOTICE redistribution=prohibited concurrent_sessions=1")
    sanma, yonma = install_tools(py, tools)
    xml = download_xml(py, cache, modes, limits)
    result = {
        "protocol": "mortal-rogs-tenhou-training-prep-v1",
        "pins": {"houou_logs": HOUOU_SHA, "sanma_converter": SANMA_SHA, "yonma_converter": YONMA_SHA},
        "modes": {},
    }
    for mode in modes:
        data = runtime / "runtime" / mode / "data" / "tenhou-houou"
        conversion = convert(mode, xml[mode], data, sanma, yonma, args.val_ratio)
        config = configure(runtime, mode, data)
        train_count, val_count = validate_data(runtime, mode, data, 16)
        baseline = prepare_baseline(
            py, runtime, mode, args.baseline_3p if mode == "3p" else args.baseline_4p
        )
        grp = train_grp(py, runtime, mode, config, args.grp_steps, args.retrain_grp)
        result["modes"][mode] = {
            "data_root": str(data), "train_files": train_count, "val_files": val_count,
            "conversion": conversion, "baseline": baseline, "grp": grp, "config": str(config),
        }
        print(f"MORTAL_TENHOU_MODE_PREPARED mode={mode} train={train_count} val={val_count} grp_steps={grp['steps']}")

    manifest = args.manifest.expanduser().resolve() if args.manifest else cache / "prepare.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"MORTAL_TENHOU_TRAINING_PREP_OK manifest={manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
