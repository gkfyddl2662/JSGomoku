from __future__ import annotations

from dataclasses import dataclass
import gzip
import json
from pathlib import Path
import re
from typing import Iterable, Mapping, Sequence


_LOG_RE = re.compile(r"^(?P<seed>\d+)_(?P<key>\d+)_(?P<split>[a-d])\.json\.gz$")
_DEFAULT_RANK_POINTS: dict[int, tuple[float, ...]] = {
    3: (6.0, 0.0, -6.0),
    4: (90.0, 45.0, 0.0, -135.0),
}


class StrengthLogError(ValueError):
    pass


@dataclass(frozen=True)
class DuplicateGameResult:
    seed: int
    seed_key: int
    seat: int
    players: int
    starting_score: float
    raw_score: float
    placement: int
    tobi: bool
    path: Path

    def paired_side(self) -> dict[str, float | int]:
        return {"placement": self.placement, "raw_score": self.raw_score}


@dataclass(frozen=True)
class PairedLogResult:
    candidate: DuplicateGameResult
    baseline: DuplicateGameResult

    @property
    def seed(self) -> int:
        return self.candidate.seed

    @property
    def seed_key(self) -> int:
        return self.candidate.seed_key

    @property
    def seat(self) -> int:
        return self.candidate.seat

    @property
    def players(self) -> int:
        return self.candidate.players


def default_rank_points(players: int) -> tuple[float, ...]:
    try:
        return _DEFAULT_RANK_POINTS[int(players)]
    except KeyError as exc:
        raise StrengthLogError(f"players must be 3 or 4, got {players}") from exc


def _split_to_seat(split: str, players: int) -> int:
    allowed = "abc" if players == 3 else "abcd" if players == 4 else ""
    if not allowed:
        raise StrengthLogError(f"players must be 3 or 4, got {players}")
    split = split.casefold()
    if split not in allowed:
        raise StrengthLogError(f"split {split!r} is invalid for {players}P")
    return allowed.index(split)


def _read_events(path: Path) -> list[dict[str, object]]:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StrengthLogError(f"failed to read MJAI log {path}: {exc}") from exc
    if not rows or not all(isinstance(row, dict) for row in rows):
        raise StrengthLogError(f"MJAI log is empty or malformed: {path}")
    return rows


def _log_identity(path: Path, players: int) -> tuple[int, int, int]:
    match = _LOG_RE.fullmatch(path.name)
    if match is None:
        raise StrengthLogError(
            f"duplicate arena log must be named <seed>_<key>_<split>.json.gz: {path.name}"
        )
    return (
        int(match.group("seed")),
        int(match.group("key")),
        _split_to_seat(match.group("split"), players),
    )


def _active_scores(values: object, players: int, *, label: str, path: Path) -> list[float]:
    if not isinstance(values, list) or len(values) < players:
        raise StrengthLogError(f"{path}: {label} must contain at least {players} scores")
    try:
        return [float(value) for value in values[:players]]
    except (TypeError, ValueError) as exc:
        raise StrengthLogError(f"{path}: {label} contains a non-numeric score") from exc


def parse_duplicate_log(path: str | Path, *, players: int) -> DuplicateGameResult:
    path = Path(path).expanduser().resolve()
    seed, seed_key, seat = _log_identity(path, players)
    events = _read_events(path)

    first = events[0]
    if first.get("type") != "start_game":
        raise StrengthLogError(f"{path}: first event is not start_game")
    logged_seed = first.get("seed")
    if logged_seed is not None:
        if not isinstance(logged_seed, list) or len(logged_seed) != 2:
            raise StrengthLogError(f"{path}: start_game.seed is malformed")
        if (int(logged_seed[0]), int(logged_seed[1])) != (seed, seed_key):
            raise StrengthLogError(
                f"{path}: filename seed {(seed, seed_key)} != start_game seed {tuple(logged_seed)}"
            )

    starting_scores: list[float] | None = None
    scores: list[float] | None = None
    for event in events:
        kind = event.get("type")
        if kind == "start_kyoku":
            current = _active_scores(event.get("scores"), players, label="start_kyoku.scores", path=path)
            if starting_scores is None:
                starting_scores = current.copy()
            scores = current
            continue
        if scores is None:
            continue
        if kind == "reach_accepted":
            actor = int(event.get("actor", -1))
            if not 0 <= actor < players:
                raise StrengthLogError(f"{path}: invalid reach_accepted actor {actor}")
            scores[actor] -= 1000.0
            continue
        if kind in {"hora", "ryukyoku"} and event.get("deltas") is not None:
            deltas = _active_scores(event.get("deltas"), players, label=f"{kind}.deltas", path=path)
            scores = [score + delta for score, delta in zip(scores, deltas, strict=True)]

    if starting_scores is None or scores is None:
        raise StrengthLogError(f"{path}: no start_kyoku event found")

    # Mortal Rankings sorts descending by score and keeps seat order for ties.
    player_by_rank = sorted(range(players), key=lambda player: (-scores[player], player))
    placement = player_by_rank.index(seat) + 1
    return DuplicateGameResult(
        seed=seed,
        seed_key=seed_key,
        seat=seat,
        players=players,
        starting_score=starting_scores[seat],
        raw_score=scores[seat],
        placement=placement,
        tobi=scores[seat] < 0,
        path=path,
    )


def index_duplicate_logs(directory: str | Path, *, players: int) -> dict[tuple[int, int, int], DuplicateGameResult]:
    directory = Path(directory).expanduser().resolve()
    if not directory.is_dir():
        raise StrengthLogError(f"duplicate log directory does not exist: {directory}")
    indexed: dict[tuple[int, int, int], DuplicateGameResult] = {}
    for path in sorted(directory.glob("*.json.gz")):
        result = parse_duplicate_log(path, players=players)
        identity = (result.seed, result.seed_key, result.seat)
        if identity in indexed:
            raise StrengthLogError(f"duplicate seed/key/seat in {directory}: {identity}")
        indexed[identity] = result
    if not indexed:
        raise StrengthLogError(f"no duplicate arena logs found in {directory}")
    return indexed


def pair_duplicate_logs(
    candidate_dir: str | Path,
    baseline_dir: str | Path,
    *,
    players: int,
) -> list[PairedLogResult]:
    candidate = index_duplicate_logs(candidate_dir, players=players)
    baseline = index_duplicate_logs(baseline_dir, players=players)
    candidate_keys = set(candidate)
    baseline_keys = set(baseline)
    if candidate_keys != baseline_keys:
        missing_candidate = sorted(baseline_keys - candidate_keys)[:8]
        missing_baseline = sorted(candidate_keys - baseline_keys)[:8]
        raise StrengthLogError(
            "candidate/baseline duplicate contexts differ; "
            f"missing_candidate={missing_candidate}, missing_baseline={missing_baseline}"
        )
    seed_keys = {key for _, key, _ in candidate_keys}
    if len(seed_keys) != 1:
        raise StrengthLogError(
            "paired promotion schema currently requires one fixed duplicate seed key per comparison; "
            f"got {sorted(seed_keys)}"
        )

    rows: list[PairedLogResult] = []
    for identity in sorted(candidate_keys):
        cand = candidate[identity]
        base = baseline[identity]
        if cand.starting_score != base.starting_score:
            raise StrengthLogError(
                f"starting score drift for seed/key/seat {identity}: "
                f"candidate={cand.starting_score}, baseline={base.starting_score}"
            )
        rows.append(PairedLogResult(cand, base))
    return rows


def paired_records(
    rows: Iterable[PairedLogResult],
    *,
    round_kind: str = "south",
    room: str = "*",
    rank: str = "*",
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    seen: set[tuple[int, int]] = set()
    for row in rows:
        key = (row.seed, row.seat)
        if key in seen:
            raise StrengthLogError(
                f"paired promotion schema cannot represent repeated seed/seat {key}; use one seed key per comparison"
            )
        seen.add(key)
        records.append(
            {
                "seed": row.seed,
                "seed_key": row.seed_key,
                "seat": row.seat,
                "players": row.players,
                "starting_score": row.candidate.starting_score,
                "round_kind": round_kind,
                "room": room,
                "rank": rank,
                "candidate": row.candidate.paired_side(),
                "baseline": row.baseline.paired_side(),
            }
        )
    if not records:
        raise StrengthLogError("paired evaluation is empty")
    return records


def strength_summary(
    games: Sequence[DuplicateGameResult],
    *,
    rank_points: Sequence[float] | None = None,
) -> dict[str, object]:
    if not games:
        raise StrengthLogError("cannot summarize an empty game set")
    players = games[0].players
    if any(game.players != players for game in games):
        raise StrengthLogError("strength summary cannot mix 3P and 4P games")
    points = tuple(default_rank_points(players) if rank_points is None else map(float, rank_points))
    if len(points) != players:
        raise StrengthLogError(f"expected {players} rank point values, got {len(points)}")

    placements = [0] * players
    total_delta_score = 0.0
    tobi = 0
    for game in games:
        if not 1 <= game.placement <= players:
            raise StrengthLogError(f"invalid placement {game.placement} for {players}P")
        placements[game.placement - 1] += 1
        total_delta_score += game.raw_score - game.starting_score
        tobi += int(game.tobi)

    count = len(games)
    total_rank_pt = sum(placements[i] * points[i] for i in range(players))
    avg_rank = sum((i + 1) * placements[i] for i in range(players)) / count
    return {
        "games": count,
        "placements": placements,
        "placement_rates": [value / count for value in placements],
        "tobi": tobi,
        "tobi_rate": tobi / count,
        "avg_rank": avg_rank,
        "total_rank_pt": total_rank_pt,
        "avg_rank_pt": total_rank_pt / count,
        "total_delta_score": total_delta_score,
        "avg_game_delta_score": total_delta_score / count,
        "rank_points": list(points),
    }


def paired_strength_report(
    rows: Sequence[PairedLogResult],
    *,
    rank_points: Sequence[float] | None = None,
) -> dict[str, object]:
    if not rows:
        raise StrengthLogError("paired evaluation is empty")
    candidate = strength_summary([row.candidate for row in rows], rank_points=rank_points)
    baseline = strength_summary([row.baseline for row in rows], rank_points=rank_points)
    return {
        "protocol": "mortal-rogs-strength-comparison-v1",
        "players": rows[0].players,
        "seed_key": rows[0].seed_key,
        "contexts": len(rows),
        "candidate": candidate,
        "baseline": baseline,
        "candidate_minus_baseline": {
            "avg_rank": float(candidate["avg_rank"]) - float(baseline["avg_rank"]),
            "avg_rank_pt": float(candidate["avg_rank_pt"]) - float(baseline["avg_rank_pt"]),
            "avg_game_delta_score": float(candidate["avg_game_delta_score"])
            - float(baseline["avg_game_delta_score"]),
            "tobi_rate": float(candidate["tobi_rate"]) - float(baseline["tobi_rate"]),
        },
    }


def _fmt(value: object, digits: int = 6) -> str:
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def render_strength_markdown(
    report: Mapping[str, object],
    *,
    candidate_name: str = "Candidate",
    baseline_name: str = "Baseline",
) -> str:
    candidate = report["candidate"]
    baseline = report["baseline"]
    if not isinstance(candidate, Mapping) or not isinstance(baseline, Mapping):
        raise StrengthLogError("invalid strength report")
    players = int(report["players"])
    lines = [
        "| Metric | " + baseline_name + " | " + candidate_name + " |",
        "|---:|---:|---:|",
        f"| Games | {_fmt(baseline['games'])} | {_fmt(candidate['games'])} |",
    ]
    base_counts = list(baseline["placements"])
    cand_counts = list(candidate["placements"])
    base_rates = list(baseline["placement_rates"])
    cand_rates = list(candidate["placement_rates"])
    for i in range(players):
        lines.append(
            f"| {i + 1}st" if i == 0 else f"| {i + 1}nd" if i == 1 else f"| {i + 1}rd" if i == 2 else f"| {i + 1}th"
        )
        lines[-1] += (
            f" (rate) | {base_counts[i]} ({base_rates[i]:.6f}) | "
            f"{cand_counts[i]} ({cand_rates[i]:.6f}) |"
        )
    lines.extend(
        [
            f"| Tobi (rate) | {baseline['tobi']} ({float(baseline['tobi_rate']):.6f}) | {candidate['tobi']} ({float(candidate['tobi_rate']):.6f}) |",
            f"| Avg rank | {float(baseline['avg_rank']):.6f} | {float(candidate['avg_rank']):.6f} |",
            f"| Total rank pt | {_fmt(baseline['total_rank_pt'])} | {_fmt(candidate['total_rank_pt'])} |",
            f"| Avg rank pt | {float(baseline['avg_rank_pt']):.6f} | {float(candidate['avg_rank_pt']):.6f} |",
            f"| Total Δscore | {_fmt(baseline['total_delta_score'])} | {_fmt(candidate['total_delta_score'])} |",
            f"| Avg game Δscore | {float(baseline['avg_game_delta_score']):.6f} | {float(candidate['avg_game_delta_score']):.6f} |",
        ]
    )
    return "\n".join(lines) + "\n"
