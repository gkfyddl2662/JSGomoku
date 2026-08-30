from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import random
import tomllib
from typing import Any, Mapping

from .platform_rating import evaluate_platform_profile
from .rating import GameResult, RatingPresetError, RatingUtility, normalized_utility


@dataclass(frozen=True)
class ObjectiveContext:
    profile: str
    players: int
    round_kind: str
    room: str
    rank: str
    specialization_probability: float
    self_rating: float | None = None
    table_average_rating: float | None = None
    games_played: int | None = None


@dataclass(frozen=True)
class RoutedUtility:
    profile: str
    raw: RatingUtility
    normalized: float
    specialization_probability: float


class RatingObjectiveRouter:
    """Choose a rating objective before a self-play game begins.

    Rating/platform metadata stays outside Mortal observations. The selected
    ObjectiveContext is attached to the generated game and reused when terminal
    utility is calculated.
    """

    def __init__(
        self,
        catalog: Mapping[str, Any],
        *,
        players: int,
        strategy: str = "universal",
        target_profile: str | None = None,
        specialize_start: float = 0.70,
        seed: int = 0,
    ) -> None:
        if players not in (3, 4):
            raise ValueError("players must be 3 or 4")
        if not 0.0 <= specialize_start <= 1.0:
            raise ValueError("specialize_start must be within [0, 1]")
        self.catalog = catalog
        self.players = players
        self.strategy = strategy.casefold()
        self.target_profile = target_profile
        self.specialize_start = specialize_start
        self.rng = random.Random(seed)
        self.profiles = catalog.get("profiles", {})
        self.contexts = catalog.get("contexts", {}).get(f"{players}p", {})
        self.universal_weights = {
            k: float(v) for k, v in catalog.get("universal", {}).get(f"{players}p", {}).items()
        }

        if self.strategy not in {"universal", "specialized", "curriculum"}:
            raise ValueError(f"Unknown rating strategy: {strategy}")
        if self.strategy in {"specialized", "curriculum"}:
            if not target_profile or target_profile not in self.profiles:
                raise RatingPresetError("specialized/curriculum requires a known target_profile")
        if self.strategy in {"universal", "curriculum"} and not self.universal_weights:
            raise RatingPresetError(f"No universal {players}P mixture configured")

    @classmethod
    def from_toml(cls, path: str | Path, **kwargs: Any) -> "RatingObjectiveRouter":
        with Path(path).open("rb") as f:
            return cls(tomllib.load(f), **kwargs)

    def specialization_probability(self, progress: float) -> float:
        progress = max(0.0, min(1.0, float(progress)))
        if self.strategy == "specialized":
            return 1.0
        if self.strategy == "universal" or progress <= self.specialize_start:
            return 0.0
        return min(1.0, (progress - self.specialize_start) / max(1e-9, 1.0 - self.specialize_start))

    def _sample_universal(self) -> str:
        names = [name for name, weight in self.universal_weights.items() if weight > 0]
        weights = [self.universal_weights[name] for name in names]
        if not names:
            raise RatingPresetError("Universal mixture contains no positive-weight profile")
        return self.rng.choices(names, weights=weights, k=1)[0]

    def choose_profile(self, progress: float) -> tuple[str, float]:
        p_special = self.specialization_probability(progress)
        if self.strategy == "specialized" or (
            self.strategy == "curriculum" and self.rng.random() < p_special
        ):
            return str(self.target_profile), p_special
        return self._sample_universal(), p_special

    def sample_objective(self, progress: float = 0.0) -> ObjectiveContext:
        profile, p_special = self.choose_profile(progress)
        options = self.contexts.get(profile, [])
        if not options:
            raise RatingPresetError(f"No {self.players}P training context configured for profile={profile!r}")
        row = self.rng.choice(options)
        return ObjectiveContext(
            profile=profile,
            players=self.players,
            round_kind=str(row.get("round", "south")),
            room=str(row.get("room", "*")),
            rank=str(row.get("rank", "*")),
            specialization_probability=p_special,
            self_rating=float(row["self_rating"]) if "self_rating" in row else None,
            table_average_rating=float(row["table_average_rating"]) if "table_average_rating" in row else None,
            games_played=int(row["games_played"]) if "games_played" in row else None,
        )

    def evaluate_bound(self, result: GameResult, objective: ObjectiveContext) -> RoutedUtility:
        if result.players != self.players or objective.players != self.players:
            raise ValueError("Player-count mismatch in bound rating objective")
        if (result.round_kind, result.room, result.rank) != (
            objective.round_kind,
            objective.room,
            objective.rank,
        ):
            raise ValueError("GameResult context does not match the objective sampled before the game")
        profile = self.profiles[objective.profile]
        raw = evaluate_platform_profile(objective.profile, profile, result)
        scale = float(profile.get("normalization_scale", 100.0))
        clip = float(self.catalog.get("catalog", {}).get("normalize_clip", 6.0))
        return RoutedUtility(
            profile=objective.profile,
            raw=raw,
            normalized=normalized_utility(raw.total, scale=scale, clip=clip),
            specialization_probability=objective.specialization_probability,
        )
