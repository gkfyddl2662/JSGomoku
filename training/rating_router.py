from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import random
import tomllib
from typing import Any, Mapping

from .platform_rating import evaluate_platform_profile
from .rating import GameResult, RatingPresetError, RatingUtility, normalized_utility


@dataclass(frozen=True)
class RoutedUtility:
    profile: str
    raw: RatingUtility
    normalized: float
    specialization_probability: float


class RatingObjectiveRouter:
    """Select platform utility targets while keeping Mortal model inputs unchanged.

    Strategies:
      universal: sample the configured platform mixture for the whole run.
      specialized: always optimize one target profile.
      curriculum: start universal and linearly anneal to the target profile.
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
        universal = catalog.get("universal", {}).get(f"{players}p", {})
        # tomllib may expose numeric-looking keys differently only if unquoted;
        # our shipped file uses quoted table names through TOML table syntax.
        if not universal:
            universal = catalog.get("universal", {}).get(str(players), {})
        self.universal_weights = {k: float(v) for k, v in universal.items()}

        if self.strategy not in {"universal", "specialized", "curriculum"}:
            raise ValueError(f"Unknown rating strategy: {strategy}")
        if self.strategy in {"specialized", "curriculum"}:
            if not target_profile or target_profile not in self.profiles:
                raise RatingPresetError("specialized/curriculum strategy requires a known target_profile")
        if self.strategy in {"universal", "curriculum"} and not self.universal_weights:
            raise RatingPresetError(f"No universal {players}P mixture configured")

    @classmethod
    def from_toml(cls, path: str | Path, **kwargs: Any) -> "RatingObjectiveRouter":
        with Path(path).open("rb") as f:
            catalog = tomllib.load(f)
        return cls(catalog, **kwargs)

    def specialization_probability(self, progress: float) -> float:
        progress = max(0.0, min(1.0, float(progress)))
        if self.strategy == "specialized":
            return 1.0
        if self.strategy == "universal":
            return 0.0
        if progress <= self.specialize_start:
            return 0.0
        span = max(1e-9, 1.0 - self.specialize_start)
        return min(1.0, (progress - self.specialize_start) / span)

    def _sample_universal(self) -> str:
        names = list(self.universal_weights)
        weights = [self.universal_weights[n] for n in names]
        if any(w < 0 for w in weights) or sum(weights) <= 0:
            raise RatingPresetError("Universal weights must be non-negative with positive sum")
        return self.rng.choices(names, weights=weights, k=1)[0]

    def choose_profile(self, progress: float) -> tuple[str, float]:
        p_special = self.specialization_probability(progress)
        if self.strategy == "specialized" or (self.strategy == "curriculum" and self.rng.random() < p_special):
            return str(self.target_profile), p_special
        return self._sample_universal(), p_special

    def evaluate(self, result: GameResult, *, progress: float = 0.0) -> RoutedUtility:
        if result.players != self.players:
            raise ValueError(f"Router is {self.players}P but result is {result.players}P")
        profile_name, p_special = self.choose_profile(progress)
        profile = self.profiles[profile_name]
        raw = evaluate_platform_profile(profile_name, profile, result)
        scale = float(profile.get("normalization_scale", 100.0))
        clip = float(self.catalog.get("catalog", {}).get("normalize_clip", 6.0))
        return RoutedUtility(
            profile=profile_name,
            raw=raw,
            normalized=normalized_utility(raw.total, scale=scale, clip=clip),
            specialization_probability=p_special,
        )
