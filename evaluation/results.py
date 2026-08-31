from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class GameResultRow:
    seed: int | None
    rankings: dict[str, int]
    scores: dict[str, int]

    @property
    def players(self) -> int:
        return len(self.rankings)


def parse_mjx_result(line: str) -> GameResultRow:
    row = json.loads(line)
    rankings = row.get("rankings", {})
    scores = row.get("tens", row.get("scores", {}))
    if not isinstance(rankings, dict) or not isinstance(scores, dict):
        raise ValueError("MJX result must contain rankings and tens maps")
    if set(rankings) != set(scores):
        raise ValueError("MJX rankings/tens player sets differ")
    if len(rankings) not in (3, 4):
        raise ValueError(f"Expected 3P or 4P result, got {len(rankings)} players")
    expected_ranks = set(range(1, len(rankings) + 1))
    actual_ranks = {int(v) for v in rankings.values()}
    if actual_ranks != expected_ranks:
        raise ValueError(f"Invalid ranking set: expected {expected_ranks}, got {actual_ranks}")
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
    player_counts = {row.players for row in rows}
    if len(player_counts) != 1:
        raise ValueError("Cannot mix 3P and 4P rows in one summary")
    players = next(iter(player_counts))
    if any(player_id not in row.rankings for row in rows):
        raise KeyError(f"Player {player_id!r} is missing from one or more rows")

    ranks = [row.rankings[player_id] for row in rows]
    scores = [row.scores[player_id] for row in rows]
    summary: dict[str, float] = {
        "games": float(len(rows)),
        "players": float(players),
        "average_rank": sum(ranks) / len(ranks),
        "average_score": sum(scores) / len(scores),
    }
    for rank in range(1, players + 1):
        summary[f"place_{rank}_rate"] = sum(x == rank for x in ranks) / len(ranks)
    summary["last_place_rate"] = summary[f"place_{players}_rate"]
    return summary
