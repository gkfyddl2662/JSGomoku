from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.prepare_selfplay_population import POPULATION_PROTOCOL, checkpoint_sha256, normalize_mode, runtime_paths

INSTALL_PROTOCOL = "mortal-rogs-population-champion-install-v1"
SLOTS = ("current.pth", "best_mortal.pth", "baseline.pth")


def _copy_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".install.tmp")
    tmp.unlink(missing_ok=True)
    shutil.copy2(source, tmp)
    tmp.replace(destination)


def _backup_existing(source: Path, backup: Path) -> None:
    backup.parent.mkdir(parents=True, exist_ok=True)
    if backup.exists():
        return
    try:
        os.link(source, backup)
    except OSError:
        shutil.copy2(source, backup)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Install a previously validated self-play population Champion into Mortal's current/best/baseline slots. "
            "Different existing checkpoints are backed up before replacement."
        )
    )
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--mode", choices=("3p", "4p"), required=True)
    parser.add_argument("--population", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    mode = normalize_mode(args.mode)
    paths = runtime_paths(args.runtime_root, mode)
    population_path = (
        args.population.expanduser().resolve()
        if args.population is not None
        else paths["population"] / "population.json"
    )
    if not population_path.is_file():
        raise SystemExit(f"population manifest does not exist: {population_path}")

    population = json.loads(population_path.read_text(encoding="utf-8"))
    if population.get("protocol") != POPULATION_PROTOCOL or population.get("mode") != mode:
        raise SystemExit("population manifest protocol/mode mismatch")
    champion_id = str(population.get("champion_id", ""))
    members = [item for item in population.get("members", []) if isinstance(item, dict)]
    champion = next((item for item in members if str(item.get("id")) == champion_id), None)
    if champion is None:
        raise SystemExit("population Champion is missing from active members")
    source = Path(str(champion.get("file", ""))).expanduser().resolve()
    if not source.is_file() or source.suffix.casefold() != ".pth":
        raise SystemExit(f"population Champion file is missing: {source}")

    expected_sha = str(champion.get("sha256", ""))
    actual_sha = checkpoint_sha256(source)
    if expected_sha and actual_sha != expected_sha:
        raise SystemExit("population Champion hash changed after validation; rebuild the population")

    models = paths["models"]
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    backup_root = models / "bootstrap-backup" / timestamp
    changes: list[dict[str, object]] = []
    for slot_name in SLOTS:
        destination = models / slot_name
        previous_sha = checkpoint_sha256(destination) if destination.is_file() else None
        if previous_sha == actual_sha:
            changes.append({
                "slot": slot_name,
                "destination": str(destination),
                "changed": False,
                "previous_sha256": previous_sha,
                "backup": None,
            })
            continue

        backup: Path | None = None
        if destination.is_file():
            backup = backup_root / slot_name
            _backup_existing(destination, backup)
        _copy_atomic(source, destination)
        installed_sha = checkpoint_sha256(destination)
        if installed_sha != actual_sha:
            raise RuntimeError(f"installed Champion hash mismatch: {destination}")
        changes.append({
            "slot": slot_name,
            "destination": str(destination),
            "changed": True,
            "previous_sha256": previous_sha,
            "backup": str(backup) if backup is not None else None,
        })
        print(
            "MORTAL_CHAMPION_SLOT_INSTALLED",
            f"mode={mode}",
            f"slot={slot_name}",
            f"backup={backup if backup is not None else 'none'}",
            flush=True,
        )

    report = {
        "protocol": INSTALL_PROTOCOL,
        "mode": mode,
        "population": str(population_path),
        "champion_id": champion_id,
        "champion_file": str(source),
        "sha256": actual_sha,
        "changes": changes,
    }
    report_path = (
        args.report.expanduser().resolve()
        if args.report is not None
        else paths["runs"] / "selfplay-data" / f"champion-install-{mode}-{timestamp}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = report_path.with_suffix(report_path.suffix + ".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(report_path)
    print(
        "MORTAL_POPULATION_CHAMPION_INSTALLED",
        f"mode={mode}",
        f"champion={champion_id}",
        f"report={report_path}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
