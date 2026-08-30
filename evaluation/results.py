from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class GameResultRow:
    seed: int | None
    rankings: dict[str, int]
    scores: dict[str, int]


def parse_mjx_result(line: str) -> GameResultRow:
    row = json.loads(line)
    rankings = row.get("rankings", {})
    scores = row.get("tens", row.get("scores", {}))
    if not isinstance(rankings, dict) or not isinstance(scores, dict):
        raise ValueError("MJX result must contain rankings and tens maps")
    seed = row.get("gameSeed", row.get("game_seed"))
    return GameResultRow(
        seed=None if seed is None else int(seed),
        rankings={str(k): int(v) for k, v in rankings.items()},
        scores={str(k): int(v) for k, v in scores.items()},
    )


def load_mjx_results(path: str | Path) -> list[GameResultRow]:
    output: list[GameResultRow] = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                output.append(parse_mjx_result(line))
    return output


def summarize_player(rows: list[GameResultRow], player_id: str) -> dict[str, float]:
    if not rows:
        raise ValueError("No evaluation rows")
    ranks = [row.rankings[player_id] for row in rows]
    scores = [row.scores[player_id] for row in rows]
    summary: dict[str, float] = {
        "games": float(len(rows)),
        "average_rank": sum(ranks) / len(ranks),
        "average_score": sum(scores) / len(scores),
    }
    for rank in (1, 2, 3, 4):
        summary[f"place_{rank}_rate"] = sum(x == rank for x in ranks) / len(ranks)
    return summary
