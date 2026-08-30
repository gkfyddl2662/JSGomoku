from __future__ import annotations

import argparse
import json
from pathlib import Path


def _snapshot(stat, *, players: int, rank_points: list[int]) -> dict[str, object]:
    rank_counts = [int(stat.rank_1), int(stat.rank_2), int(stat.rank_3)]
    if players == 4:
        rank_counts.append(int(stat.rank_4))
    games = int(stat.game)
    return {
        "games": games,
        "rounds": int(stat.round),
        "rounds_as_dealer": int(stat.oya),
        "rank_counts": rank_counts,
        "rank_rates": [count / games for count in rank_counts] if games else [0.0] * players,
        "tobi": int(stat.tobi),
        "tobi_rate": float(stat.tobi_rate) if games else 0.0,
        "avg_rank": float(stat.avg_rank) if games else 0.0,
        "total_rank_pt": int(stat.total_pt(rank_points)) if games else 0,
        "avg_rank_pt": float(stat.avg_pt(rank_points)) if games else 0.0,
        "total_delta_score": int(stat.point),
        "avg_game_delta_score": float(stat.avg_point_per_game) if games else 0.0,
        "avg_round_delta_score": float(stat.avg_point_per_round) if int(stat.round) else 0.0,
        "win_rate": float(stat.agari_rate) if int(stat.round) else 0.0,
        "deal_in_rate": float(stat.houjuu_rate) if int(stat.round) else 0.0,
        "call_rate": float(stat.fuuro_rate) if int(stat.round) else 0.0,
        "riichi_rate": float(stat.riichi_rate) if int(stat.round) else 0.0,
        "ryukyoku_rate": float(stat.ryukyoku_rate) if int(stat.round) else 0.0,
        "native_table": str(stat),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export Mortal/libriichi Stat tables for two duplicate-evaluation log sets."
    )
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--candidate-name", required=True)
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--baseline-name", required=True)
    parser.add_argument("--mode", choices=("3p", "4p"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        from libriichi import stat as libriichi_stat
    except ImportError as exc:
        raise SystemExit(
            "libriichi is unavailable. Run this script with the unified Mortal runtime Python."
        ) from exc
    Stat = libriichi_stat.Stat

    players = 3 if args.mode == "3p" else 4
    rank_points = [6, 0, -6] if players == 3 else [90, 45, 0, -135]
    candidate_dir = args.candidate_dir.expanduser().resolve()
    baseline_dir = args.baseline_dir.expanduser().resolve()
    if not candidate_dir.is_dir():
        raise SystemExit(f"candidate log directory does not exist: {candidate_dir}")
    if not baseline_dir.is_dir():
        raise SystemExit(f"baseline log directory does not exist: {baseline_dir}")

    candidate = Stat.from_dir(str(candidate_dir), args.candidate_name, True)
    baseline = Stat.from_dir(str(baseline_dir), args.baseline_name, True)
    candidate_snapshot = _snapshot(candidate, players=players, rank_points=rank_points)
    baseline_snapshot = _snapshot(baseline, players=players, rank_points=rank_points)

    report = {
        "protocol": "mortal-rogs-native-stat-comparison-v1",
        "mode": args.mode,
        "players": players,
        "rank_points": rank_points,
        "candidate_name": args.candidate_name,
        "baseline_name": args.baseline_name,
        "candidate_dir": str(candidate_dir),
        "baseline_dir": str(baseline_dir),
        "candidate": candidate_snapshot,
        "baseline": baseline_snapshot,
        "candidate_minus_baseline": {
            "avg_rank": float(candidate_snapshot["avg_rank"]) - float(baseline_snapshot["avg_rank"]),
            "avg_rank_pt": float(candidate_snapshot["avg_rank_pt"]) - float(baseline_snapshot["avg_rank_pt"]),
            "avg_game_delta_score": float(candidate_snapshot["avg_game_delta_score"])
            - float(baseline_snapshot["avg_game_delta_score"]),
            "win_rate": float(candidate_snapshot["win_rate"]) - float(baseline_snapshot["win_rate"]),
            "deal_in_rate": float(candidate_snapshot["deal_in_rate"])
            - float(baseline_snapshot["deal_in_rate"]),
            "call_rate": float(candidate_snapshot["call_rate"]) - float(baseline_snapshot["call_rate"]),
            "riichi_rate": float(candidate_snapshot["riichi_rate"])
            - float(baseline_snapshot["riichi_rate"]),
        },
    }

    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    text_output = output.with_suffix(".txt")
    text_output.write_text(
        f"# {args.baseline_name}\n\n{baseline_snapshot['native_table']}\n\n"
        f"# {args.candidate_name}\n\n{candidate_snapshot['native_table']}\n",
        encoding="utf-8",
    )
    print(
        "MORTAL_NATIVE_STAT_REPORT_OK",
        f"mode={args.mode}",
        f"candidate_games={candidate_snapshot['games']}",
        f"baseline_games={baseline_snapshot['games']}",
        f"output={output}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
