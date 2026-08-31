from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.strength import (
    default_rank_points,
    pair_duplicate_logs,
    paired_records,
    paired_strength_report,
    render_strength_markdown,
)


def _rank_points(raw: str | None, players: int) -> tuple[float, ...]:
    if raw is None or not raw.strip():
        return default_rank_points(players)
    values = tuple(float(part.strip()) for part in raw.split(",") if part.strip())
    if len(values) != players:
        raise SystemExit(f"--rank-points requires exactly {players} comma-separated values")
    return values


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Pair two Mortal duplicate-evaluation log directories by seed/key/seat and emit "
            "promotion JSONL plus a Mortal-docs-style strength summary."
        )
    )
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=("3p", "4p"), required=True)
    parser.add_argument("--output", type=Path, required=True, help="Paired JSONL for promotion_gate.py")
    parser.add_argument("--summary-json", type=Path)
    parser.add_argument("--summary-md", type=Path)
    parser.add_argument("--candidate-name", default="Candidate")
    parser.add_argument("--baseline-name", default="Baseline")
    parser.add_argument("--round-kind", default="south")
    parser.add_argument("--room", default="*")
    parser.add_argument("--rank", default="*")
    parser.add_argument(
        "--rank-points",
        help="Comma-separated placement points; defaults to 3P [6,0,-6] or Mortal 4P [90,45,0,-135]",
    )
    args = parser.parse_args()

    players = 3 if args.mode == "3p" else 4
    rank_points = _rank_points(args.rank_points, players)
    rows = pair_duplicate_logs(args.candidate_dir, args.baseline_dir, players=players)
    records = paired_records(
        rows,
        round_kind=args.round_kind,
        room=args.room,
        rank=args.rank,
    )
    report = paired_strength_report(rows, rank_points=rank_points)
    report.update(
        {
            "mode": args.mode,
            "candidate_name": args.candidate_name,
            "baseline_name": args.baseline_name,
            "candidate_dir": str(args.candidate_dir.expanduser().resolve()),
            "baseline_dir": str(args.baseline_dir.expanduser().resolve()),
            "paired_output": str(args.output.expanduser().resolve()),
            "round_kind": args.round_kind,
            "room": args.room,
            "rank": args.rank,
        }
    )

    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n" for record in records),
        encoding="utf-8",
    )

    summary_json = (
        args.summary_json.expanduser().resolve()
        if args.summary_json is not None
        else output.with_suffix(".summary.json")
    )
    summary_md = (
        args.summary_md.expanduser().resolve()
        if args.summary_md is not None
        else output.with_suffix(".summary.md")
    )
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_md.parent.mkdir(parents=True, exist_ok=True)
    summary_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary_md.write_text(
        render_strength_markdown(
            report,
            candidate_name=args.candidate_name,
            baseline_name=args.baseline_name,
        ),
        encoding="utf-8",
    )

    print(
        "MORTAL_PAIRED_EVALUATION_OK",
        f"mode={args.mode}",
        f"contexts={len(records)}",
        f"seed_key={report['seed_key']}",
        f"output={output}",
    )
    print(
        "MORTAL_STRENGTH_REPORT_OK",
        f"summary_json={summary_json}",
        f"summary_md={summary_md}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
