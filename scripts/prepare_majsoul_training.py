from __future__ import annotations

import argparse
import getpass
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.prepare_tenhou_training import (  # noqa: E402
    checkout,
    configure,
    prepare_baseline,
    split_for,
    train_grp,
    validate_data,
)

MAJSOUL_TOOL_REPO = "https://github.com/NikkeTryHard/tenhou-to-mjai.git"
MAJSOUL_TOOL_SHA = "69fb75a51c7efef3212be603227b2a58a9717237"
AMAE_API_ROOT = "https://5-data.amae-koromo.com/api/v2"
MODE_SOURCES = {
    "3p": {"api": "pl3", "players": 3, "min_date": "2019-11-29",
           "rooms": (("throne", 26), ("jade", 24), ("gold", 22))},
    "4p": {"api": "pl4", "players": 4, "min_date": "2019-08-23",
           "rooms": (("throne", 16), ("jade", 12), ("gold", 9))},
}
API_LIMIT = 500
MIN_WINDOW_MS = 5 * 60 * 1000
USER_AGENT = "Mortal-ROGS/1.0 local-training-prep"


class ApiRateLimiter:
    def __init__(self, rps: float) -> None:
        if not 0 < rps <= 4:
            raise ValueError("Amae-Koromo RPS must be in (0, 4]")
        self.interval = 1.0 / rps
        self.last_started: float | None = None

    def wait(self) -> None:
        if self.last_started is not None:
            remaining = self.interval - (time.monotonic() - self.last_started)
            if remaining > 0:
                time.sleep(remaining)
        self.last_started = time.monotonic()


def fetch_json(url: str, limiter: ApiRateLimiter) -> object:
    for attempt in range(5):
        limiter.wait()
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code != 429 and exc.code < 500:
                raise
            if attempt == 4:
                raise
            time.sleep(min(8.0, 0.5 * (2**attempt)))
        except (TimeoutError, urllib.error.URLError):
            if attempt == 4:
                raise
            time.sleep(min(8.0, 0.5 * (2**attempt)))
    raise RuntimeError("unreachable")


def room_url(mode: str, room_mode: int, start_ms: int, end_ms: int) -> str:
    query = urllib.parse.urlencode({"mode": room_mode, "limit": API_LIMIT})
    return f"{AMAE_API_ROOT}/{MODE_SOURCES[mode]['api']}/games/{start_ms}/{end_ms}?{query}"


def fetch_window(mode: str, room_mode: int, start_ms: int, end_ms: int, limiter: ApiRateLimiter) -> list[dict]:
    payload = fetch_json(room_url(mode, room_mode, start_ms, end_ms), limiter)
    if not isinstance(payload, list):
        raise RuntimeError(f"unexpected Amae-Koromo response for {mode}: {type(payload).__name__}")
    records = [x for x in payload if isinstance(x, dict) and isinstance(x.get("uuid"), str)]
    if len(records) < API_LIMIT:
        return records
    if end_ms - start_ms <= MIN_WINDOW_MS:
        raise RuntimeError(
            f"Amae-Koromo cap still reached in <=5m window: mode={mode} room={room_mode}"
        )
    middle = start_ms + (end_ms - start_ms) // 2
    merged = {}
    for item in (
        fetch_window(mode, room_mode, start_ms, middle, limiter)
        + fetch_window(mode, room_mode, middle + 1, end_ms, limiter)
    ):
        merged[item["uuid"]] = item
    return list(merged.values())


def utc_day_bounds(day: date) -> tuple[int, int]:
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1) - timedelta(milliseconds=1)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def collect_uuids(mode: str, target: int, cache: Path, end_day: date, api_rps: float) -> dict:
    mode_cache = cache / mode
    mode_cache.mkdir(parents=True, exist_ok=True)
    todo = mode_cache / "todo.txt"
    metadata = mode_cache / "discovery.jsonl"
    known: dict[str, dict] = {}
    if metadata.is_file():
        for line in metadata.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and isinstance(item.get("uuid"), str):
                known[item["uuid"]] = item

    source = MODE_SOURCES[mode]
    limiter = ApiRateLimiter(api_rps)
    seen = set(known)
    oldest = date.fromisoformat(source["min_date"])
    expected_players = int(source["players"])

    for room_name, room_mode in source["rooms"]:
        if len(known) >= target:
            break
        day = end_day
        while day >= oldest and len(known) < target:
            start_ms, end_ms = utc_day_bounds(day)
            records = fetch_window(mode, room_mode, start_ms, end_ms, limiter)
            records = [
                r for r in records
                if int(r.get("modeId", room_mode)) == room_mode
                and len(r.get("players", [])) == expected_players
            ]
            records.sort(key=lambda r: int(r.get("startTime", 0)), reverse=True)
            added = 0
            for record in records:
                if record["uuid"] in seen:
                    continue
                seen.add(record["uuid"])
                item = dict(record)
                item["_source_room"] = room_name
                item["_source_mode_id"] = room_mode
                known[item["uuid"]] = item
                added += 1
                if len(known) >= target:
                    break
            print(
                f"MAJSOUL_DISCOVERY mode={mode} room={room_name} date={day} "
                f"new={added} total={len(known)}/{target}",
                flush=True,
            )
            day -= timedelta(days=1)

    rank = {"throne": 0, "jade": 1, "gold": 2}
    ordered = sorted(
        known.values(),
        key=lambda r: (rank.get(str(r.get("_source_room")), 9), -int(r.get("startTime", 0)), r["uuid"]),
    )
    selected = ordered[:target]
    if len(selected) < target:
        raise RuntimeError(f"{mode} discovery shortfall: {len(selected)}/{target}")

    todo.write_text("\n".join(r["uuid"] for r in selected) + "\n", encoding="utf-8")
    with metadata.open("w", encoding="utf-8", newline="\n") as f:
        for item in ordered:
            f.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")

    rooms: dict[str, int] = {}
    for item in selected:
        name = str(item.get("_source_room", "unknown"))
        rooms[name] = rooms.get(name, 0) + 1
    print(f"MAJSOUL_UUIDS_READY mode={mode} selected={len(selected)} rooms={rooms}", flush=True)
    return {"todo": todo, "metadata": metadata, "selected": len(selected), "rooms": rooms}


def install_tool(tools: Path) -> Path:
    source = checkout(tools / "tenhou-to-mjai", MAJSOUL_TOOL_REPO, MAJSOUL_TOOL_SHA)
    target = tools / "target"
    exe = target / "release" / ("tenhou-scraper.exe" if os.name == "nt" else "tenhou-scraper")
    marker = tools / f".built-{MAJSOUL_TOOL_SHA}"
    if not exe.is_file() or not marker.is_file():
        env = os.environ.copy()
        env["CARGO_TARGET_DIR"] = str(target)
        print("+ cargo build --release --locked [pinned Majsoul tool]", flush=True)
        subprocess.run(["cargo", "build", "--release", "--locked"], cwd=source, env=env, check=True)
        marker.write_text(MAJSOUL_TOOL_SHA + "\n", encoding="utf-8")
    return exe


def read_credentials(account: str | None) -> tuple[str, str]:
    username = (account or os.environ.get("MORTAL_ROGS_MAJSOUL_USERNAME", "")).strip()
    if not username:
        if not sys.stdin.isatty():
            raise RuntimeError("set MORTAL_ROGS_MAJSOUL_USERNAME for non-interactive use")
        username = input("Mahjong Soul native account/email: ").strip()
    password = os.environ.get("MORTAL_ROGS_MAJSOUL_PASSWORD", "")
    if not password:
        if not sys.stdin.isatty():
            raise RuntimeError("set MORTAL_ROGS_MAJSOUL_PASSWORD for non-interactive use")
        password = getpass.getpass("Mahjong Soul password: ")
    if not username or not password:
        raise RuntimeError("Mahjong Soul username/password cannot be empty")
    return username, password


def download_raw(
    exe: Path, mode: str, todo: Path, cache: Path, username: str, password: str, server: str, delay_ms: int
) -> Path:
    base = cache / mode
    raw = base / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    completed = base / "completed.log"
    db = base / "tool.db"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".accounts.txt") as f:
        f.write(username + "\n")
        accounts = Path(f.name)
    try:
        cmd = [
            str(exe), "-d", str(db), "majsoul", "raw-download",
            "--accounts", str(accounts), "--password", password,
            "--todo", str(todo), "--completed", str(completed),
            "--output", str(raw), "--server", server, "--delay-ms", str(delay_ms),
        ]
        shown = cmd.copy()
        shown[shown.index("--password") + 1] = "<redacted>"
        print("+", subprocess.list2cmdline(shown), flush=True)
        subprocess.run(cmd, cwd=base, check=True)
    finally:
        accounts.unlink(missing_ok=True)

    uuids = [x.strip() for x in todo.read_text(encoding="utf-8").splitlines() if x.strip()]
    missing = [u for u in uuids if not (raw / f"{u.replace('-', '_')}.pb").is_file()]
    if missing:
        raise RuntimeError(f"{mode} raw download incomplete: missing={len(missing)}/{len(uuids)}; rerun is resumable")
    return raw


def convert_raw(exe: Path, mode: str, cache: Path, raw: Path) -> Path:
    base = cache / mode
    out = base / "mjai"
    out.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(exe), "-d", str(base / "tool.db"), "majsoul", "convert-raw",
        "--input", str(raw), "--output", str(out),
    ]
    print("+", subprocess.list2cmdline(cmd), flush=True)
    subprocess.run(cmd, cwd=base, check=True)
    return out


def stage_mjai(mode: str, source: Path, data: Path, todo: Path, val_ratio: float) -> dict:
    expected = int(MODE_SOURCES[mode]["players"])
    uuids = [x.strip() for x in todo.read_text(encoding="utf-8").splitlines() if x.strip()]
    inputs = [source / f"{u.replace('-', '_')}.mjai.json" for u in uuids]
    missing = [p for p in inputs if not p.is_file()]
    if missing:
        raise RuntimeError(f"{mode} converter output incomplete: missing={len(missing)}/{len(inputs)}")

    desired: set[Path] = set()
    for src in inputs:
        desired.add(data / split_for(src.name, val_ratio) / f"{src.stem}.json.gz")
    for split in ("train", "val"):
        for stale in (data / split).glob("*.json.gz"):
            if stale not in desired:
                stale.unlink()

    done = reused = failed = 0
    errors: list[str] = []
    for src in inputs:
        dst = data / split_for(src.name, val_ratio) / f"{src.stem}.json.gz"
        if dst.is_file() and dst.stat().st_size > 32:
            reused += 1
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(dst.suffix + ".tmp")
        try:
            with src.open("r", encoding="utf-8") as inp:
                first_line = inp.readline()
                header = json.loads(first_line)
                if header.get("type") != "start_game" or len(header.get("names", [])) != expected:
                    raise RuntimeError("MJAI player-count/header mismatch")
                with gzip.open(tmp, "wt", encoding="utf-8", newline="\n") as out:
                    out.write(first_line.rstrip("\n") + "\n")
                    shutil.copyfileobj(inp, out)
            tmp.replace(dst)
            done += 1
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            failed += 1
            errors.append(f"{src.name}: {type(exc).__name__}: {exc}")

    total = done + reused + failed
    if errors:
        data.mkdir(parents=True, exist_ok=True)
        (data / "conversion-errors.txt").write_text("\n".join(errors) + "\n", encoding="utf-8")
    if total == 0 or failed / total > 0.05:
        raise RuntimeError(f"{mode} staging failure rate too high: {failed}/{total}")
    return {"converted": done, "reused": reused, "failed": failed}


def main() -> int:
    p = argparse.ArgumentParser(description="Prepare local Mahjong Soul high-rank logs for Mortal-ROGS.")
    p.add_argument("--runtime-root", type=Path, required=True)
    p.add_argument("--modes", choices=("both", "3p", "4p"), default="both")
    p.add_argument("--limit-3p", type=int, default=5000)
    p.add_argument("--limit-4p", type=int, default=5000)
    p.add_argument("--grp-steps", type=int, default=10000)
    p.add_argument("--val-ratio", type=float, default=0.05)
    p.add_argument("--api-rps", type=float, default=4.0)
    p.add_argument("--download-delay-ms", type=int, default=300)
    p.add_argument("--end-date", help="YYYY-MM-DD; defaults to yesterday UTC")
    p.add_argument("--server", choices=("cn", "en", "jp"), default="cn")
    p.add_argument("--account")
    p.add_argument("--baseline-3p", type=Path)
    p.add_argument("--baseline-4p", type=Path)
    p.add_argument("--retrain-grp", action="store_true")
    p.add_argument("--authorized-local-use", action="store_true")
    p.add_argument("--manifest", type=Path)
    args = p.parse_args()

    if not args.authorized_local_use:
        raise SystemExit("Pass --authorized-local-use only for permitted local access; do not redistribute logs.")
    if min(args.limit_3p, args.limit_4p, args.grp_steps, args.download_delay_ms) <= 0:
        raise SystemExit("limits, GRP steps and download delay must be positive")
    if not 0 < args.val_ratio < 0.5 or not 0 < args.api_rps <= 4:
        raise SystemExit("val-ratio must be in (0,0.5) and api-rps in (0,4]")

    runtime = args.runtime_root.expanduser().resolve()
    py = runtime / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not py.is_file():
        raise SystemExit(f"runtime Python missing: {py}")
    modes = ["3p", "4p"] if args.modes == "both" else [args.modes]
    limits = {"3p": args.limit_3p, "4p": args.limit_4p}
    tools = runtime / "runtime" / "tools" / "majsoul-prep"
    cache = runtime / "runtime" / "majsoul-cache"
    end_day = date.fromisoformat(args.end_date) if args.end_date else datetime.now(timezone.utc).date() - timedelta(days=1)

    print("MAJSOUL_LOCAL_DATA_NOTICE redistribution=prohibited credentials_persisted=false api_rps<=4")
    exe = install_tool(tools)
    username, password = read_credentials(args.account)
    result = {
        "protocol": "mortal-rogs-majsoul-training-prep-v1",
        "source": "majsoul",
        "tool": {"repository": MAJSOUL_TOOL_REPO, "commit": MAJSOUL_TOOL_SHA},
        "api_root": AMAE_API_ROOT,
        "server": args.server,
        "end_date": end_day.isoformat(),
        "credentials_persisted": False,
        "modes": {},
    }
    try:
        for mode in modes:
            discovery = collect_uuids(mode, limits[mode], cache, end_day, args.api_rps)
            raw = download_raw(
                exe, mode, discovery["todo"], cache, username, password, args.server, args.download_delay_ms
            )
            converted = convert_raw(exe, mode, cache, raw)
            data = runtime / "runtime" / mode / "data" / "majsoul-high-rank"
            staging = stage_mjai(mode, converted, data, discovery["todo"], args.val_ratio)
            config = configure(runtime, mode, data)
            train_count, val_count = validate_data(runtime, mode, data, 16)

            requested = args.baseline_3p if mode == "3p" else args.baseline_4p
            existing = runtime / "runtime" / mode / "models" / "baseline.pth"
            if requested is None and existing.is_file():
                requested = existing
            baseline = prepare_baseline(py, runtime, mode, requested)
            grp = train_grp(py, runtime, mode, config, args.grp_steps, args.retrain_grp)

            result["modes"][mode] = {
                "data_root": str(data),
                "train_files": train_count,
                "val_files": val_count,
                "rooms": discovery["rooms"],
                "staging": staging,
                "baseline": baseline,
                "grp": grp,
                "config": str(config),
            }
            print(
                f"MORTAL_MAJSOUL_MODE_PREPARED mode={mode} "
                f"train={train_count} val={val_count} grp_steps={grp['steps']}",
                flush=True,
            )
    finally:
        password = ""
        os.environ.pop("MORTAL_ROGS_MAJSOUL_PASSWORD", None)

    manifest = args.manifest.expanduser().resolve() if args.manifest else cache / "prepare.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"MORTAL_MAJSOUL_TRAINING_PREP_OK manifest={manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
