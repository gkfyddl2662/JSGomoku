from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any


BLOCKER_PATTERNS: dict[str, tuple[str, ...]] = {
    "include/mjx/env.cpp": (
        r'player_0.*player_1.*player_2.*player_3',
        r'\{1,\s*90\}.*\{2,\s*45\}.*\{3,\s*0\}.*\{4,\s*-135\}',
        r'num_ranking\.at\(4\)',
    ),
    "include/mjx/internal/state.h": (
        r'std::array<int,\s*4>\s+tens',
        r'std::array<Player,\s*4>\s+players_',
        r'rankings;\s*//\s*1~4',
    ),
    "include/mjx/internal/wall.cpp": (
        r'%\s*4',
        r'122\s*-\s*num_kan_draw_',
        r'130\s*-\s*num_kan_dora_',
    ),
    "include/mjx/internal/wall.h": (
        r'draw_ix_\s*=\s*52',
        r'136 tiles',
    ),
    "include/mjx/internal/tile.cpp": (
        r'std::vector<TileId>\(136\)',
    ),
    "mjx/env.py": (
        r'len\(agent_addresses\)\s*==\s*4',
        r'player_0.*player_1.*player_2.*player_3',
    ),
}


def git_blob_sha(path: Path) -> str:
    proc = subprocess.run(
        ["git", "hash-object", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def load_manifest(path: Path) -> dict[str, Any]:
    with path.open("rb") as f:
        return tomllib.load(f)


def audit(root: Path, manifest_path: Path) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    expected_files: dict[str, str] = manifest.get("files", {})
    hashes: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []

    for rel, expected_sha in expected_files.items():
        path = root / rel
        exists = path.is_file()
        actual_sha = git_blob_sha(path) if exists else None
        hashes.append(
            {
                "path": rel,
                "exists": exists,
                "expected": expected_sha,
                "actual": actual_sha,
                "matches_upstream": actual_sha == expected_sha,
            }
        )

    for rel, patterns in BLOCKER_PATTERNS.items():
        path = root / rel
        if not path.is_file():
            blockers.append({"path": rel, "pattern": "<missing>", "count": 1})
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in patterns:
            matches = re.findall(pattern, text, flags=re.IGNORECASE | re.DOTALL)
            if matches:
                blockers.append({"path": rel, "pattern": pattern, "count": len(matches)})

    missing = [row for row in hashes if not row["exists"]]
    upstream_changed = [row for row in hashes if row["exists"] and not row["matches_upstream"]]
    return {
        "root": str(root),
        "manifest": str(manifest_path),
        "upstream": manifest.get("upstream", {}),
        "hashes": hashes,
        "missing_files": missing,
        "changed_from_pinned_upstream": upstream_changed,
        "four_player_blockers": blockers,
        "ready_for_unmodified_patch": not missing and not upstream_changed,
        "sanma_generalization_complete": len(blockers) == 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True, help="MJX source checkout")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "mjx_sanma" / "manifest.toml",
    )
    parser.add_argument("--allow-changed", action="store_true")
    parser.add_argument("--allow-blockers", action="store_true")
    args = parser.parse_args()

    result = audit(args.root.resolve(), args.manifest.resolve())
    print(json.dumps(result, indent=2, ensure_ascii=False))

    if result["missing_files"]:
        return 2
    if result["changed_from_pinned_upstream"] and not args.allow_changed:
        return 3
    if result["four_player_blockers"] and not args.allow_blockers:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
