from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import tomllib
from typing import Any, Iterable, Mapping

from training.platform_rating import evaluate_platform_profile
from training.rating import GameResult

from .gating import PairedSample, PromotionDecision, build_standard_gate


@dataclass(frozen=True)
class SideResult:
    placement: int
    raw_score: float
    self_rating: float | None = None
    table_average_rating: float | None = None
    games_played: int | None = None


@dataclass(frozen=True)
class PairedGameRecord:
    seed: int
    seat: int
    players: int
    starting_score: float
    round_kind: str
    room: str
    rank: str
    candidate: SideResult
    baseline: SideResult

    @property
    def group(self) -> str:
        return f"{self.seed}:{self.seat}"


def _side(raw: Mapping[str, Any]) -> SideResult:
    return SideResult(
        placement=int(raw["placement"]),
        raw_score=float(raw["raw_score"]),
        self_rating=None if raw.get("self_rating") is None else float(raw["self_rating"]),
        table_average_rating=(
            None if raw.get("table_average_rating") is None else float(raw["table_average_rating"])
        ),
        games_played=None if raw.get("games_played") is None else int(raw["games_played"]),
    )


def parse_paired_record(line: str) -> PairedGameRecord:
    raw = json.loads(line)
    players = int(raw["players"])
    seat = int(raw["seat"])
    if players not in (3, 4):
        raise ValueError(f"players must be 3 or 4, got {players}")
    if not 0 <= seat < players:
        raise ValueError(f"seat must be in 0..{players - 1}, got {seat}")
    record = PairedGameRecord(
        seed=int(raw["seed"]),
        seat=seat,
        players=players,
        starting_score=float(raw["starting_score"]),
        round_kind=str(raw.get("round_kind", "south")),
        room=str(raw.get("room", "*")),
        rank=str(raw.get("rank", "*")),
        candidate=_side(raw["candidate"]),
        baseline=_side(raw["baseline"]),
    )
    for side in (record.candidate, record.baseline):
        if not 1 <= side.placement <= players:
            raise ValueError(f"placement {side.placement} is invalid for {players}P")
    return record


def load_paired_records(path: str | Path) -> list[PairedGameRecord]:
    rows: list[PairedGameRecord] = []
    seen: set[tuple[int, int]] = set()
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = parse_paired_record(line)
            key = (row.seed, row.seat)
            if key in seen:
                raise ValueError(f"Duplicate paired context seed={row.seed} seat={row.seat}")
            seen.add(key)
            rows.append(row)
    if not rows:
        raise ValueError("Paired evaluation file is empty")
    player_counts = {row.players for row in rows}
    if len(player_counts) != 1:
        raise ValueError("A paired evaluation gate cannot mix 3P and 4P records")
    return rows


def load_rating_profiles(path: str | Path) -> Mapping[str, Mapping[str, Any]]:
    with Path(path).open("rb") as f:
        cfg = tomllib.load(f)
    profiles = cfg.get("profiles")
    if not isinstance(profiles, Mapping):
        raise ValueError("rating preset file has no [profiles] table")
    return profiles


def _game_result(row: PairedGameRecord, side: SideResult) -> GameResult:
    return GameResult(
        players=row.players,
        placement=side.placement,
        raw_score=side.raw_score,
        starting_score=row.starting_score,
        round_kind=row.round_kind,
        room=row.room,
        rank=row.rank,
        self_rating=side.self_rating,
        table_average_rating=side.table_average_rating,
        games_played=side.games_played,
    )


def paired_metric_samples(
    rows: Iterable[PairedGameRecord],
    *,
    profile_name: str,
    profile: Mapping[str, Any],
) -> tuple[list[PairedSample], list[PairedSample], list[PairedSample]]:
    utility: list[PairedSample] = []
    average_rank: list[PairedSample] = []
    last_place: list[PairedSample] = []
    for row in rows:
        candidate_utility = evaluate_platform_profile(
            profile_name, profile, _game_result(row, row.candidate)
        ).total
        baseline_utility = evaluate_platform_profile(
            profile_name, profile, _game_result(row, row.baseline)
        ).total
        utility.append(PairedSample(candidate_utility, baseline_utility, row.seed, row.group))
        average_rank.append(
            PairedSample(float(row.candidate.placement), float(row.baseline.placement), row.seed, row.group)
        )
        last = row.players
        last_place.append(
            PairedSample(
                1.0 if row.candidate.placement == last else 0.0,
                1.0 if row.baseline.placement == last else 0.0,
                row.seed,
                row.group,
            )
        )
    return utility, average_rank, last_place


def evaluate_promotion_records(
    rows: Iterable[PairedGameRecord],
    *,
    profile_name: str,
    profile: Mapping[str, Any],
    resamples: int = 5000,
    confidence: float = 0.95,
    min_rating_mean: float = 0.0,
    min_rating_lower: float = 0.0,
    min_rank_improvement: float = 0.0,
    max_last_place_regression: float = 0.003,
    bootstrap_seed: int = 0,
) -> PromotionDecision:
    utility, avg_rank, last_place = paired_metric_samples(
        rows, profile_name=profile_name, profile=profile
    )
    return build_standard_gate(
        rating_utility=utility,
        average_rank=avg_rank,
        last_place_rate=last_place,
        resamples=resamples,
        confidence=confidence,
        min_rating_mean=min_rating_mean,
        min_rating_lower=min_rating_lower,
        min_rank_improvement=min_rank_improvement,
        max_last_place_regression=max_last_place_regression,
        seed=bootstrap_seed,
    )
