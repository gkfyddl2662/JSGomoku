from __future__ import annotations

from dataclasses import dataclass, field
import math
import random
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class GameResult:
    """Terminal result/context used to convert a game into training utility.

    `placement` is 1-based. `round_kind` should normally be `east` or `south`.
    Rank/room strings are preset-defined, so the training pipeline can preserve
    platform terminology without changing the Mortal observation ABI.
    """

    players: int
    placement: int
    raw_score: float
    starting_score: float
    round_kind: str = "south"
    room: str = "*"
    rank: str = "*"
    self_rating: float | None = None
    table_average_rating: float | None = None
    games_played: int | None = None

    def __post_init__(self) -> None:
        if self.players not in (3, 4):
            raise ValueError(f"players must be 3 or 4, got {self.players}")
        if not 1 <= self.placement <= self.players:
            raise ValueError(f"placement must be in 1..{self.players}, got {self.placement}")


@dataclass(frozen=True)
class RatingUtility:
    total: float
    components: Mapping[str, float] = field(default_factory=dict)
    profile: str = ""


class RatingPresetError(ValueError):
    pass


def _as_float_list(value: Any, expected: int, field_name: str) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise RatingPresetError(f"{field_name} must be a sequence")
    rows = [float(x) for x in value]
    if len(rows) != expected:
        raise RatingPresetError(f"{field_name} must contain {expected} values, got {len(rows)}")
    return rows


def _match_rule(rule: Mapping[str, Any], result: GameResult) -> bool:
    selectors = {
        "players": result.players,
        "round": result.round_kind,
        "room": result.room,
        "rank": result.rank,
    }
    for key, actual in selectors.items():
        expected = rule.get(key, "*")
        if expected == "*":
            continue
        if key == "players":
            if int(expected) != int(actual):
                return False
        elif str(expected).casefold() != str(actual).casefold():
            return False
    return True


def _specificity(rule: Mapping[str, Any]) -> int:
    return sum(rule.get(k, "*") != "*" for k in ("players", "round", "room", "rank"))


def _select_rule(profile_name: str, rules: Sequence[Mapping[str, Any]], result: GameResult) -> Mapping[str, Any]:
    matches = [(idx, r) for idx, r in enumerate(rules) if _match_rule(r, result)]
    if not matches:
        raise RatingPresetError(
            f"No rating rule in profile={profile_name!r} matches players={result.players}, "
            f"round={result.round_kind!r}, room={result.room!r}, rank={result.rank!r}. "
            "Refusing to guess a platform rating rule."
        )
    # Most-specific wins. Later rules win ties, making intentional overrides easy.
    _, best = max(matches, key=lambda item: (_specificity(item[1]), item[0]))
    return best


def table_utility(profile_name: str, cfg: Mapping[str, Any], result: GameResult) -> RatingUtility:
    """Generic platform utility: score term + uma + context-matched placement term.

    This represents Mahjong Soul / Riichi City / Amatsuki-style systems without
    putting platform metadata into Mortal's neural-network input.
    """

    rules = cfg.get("rules", [])
    if not isinstance(rules, Sequence):
        raise RatingPresetError(f"{profile_name}.rules must be a sequence")
    rule = _select_rule(profile_name, rules, result)

    placement = result.placement - 1
    uma_key = "uma_3p" if result.players == 3 else "uma_4p"
    uma = _as_float_list(cfg.get(uma_key, [0.0] * result.players), result.players, f"{profile_name}.{uma_key}")
    placement_points = _as_float_list(rule["placement"], result.players, f"{profile_name}.rule.placement")

    score_divisor = float(cfg.get("score_divisor", 0.0))
    score_weight = float(cfg.get("score_weight", 1.0))
    score_component = 0.0
    if score_divisor > 0:
        score_component = (result.raw_score - result.starting_score) / score_divisor * score_weight

    components = {
        "score": score_component,
        "uma": uma[placement],
        "placement": placement_points[placement],
    }
    total = sum(components.values())

    rounding = str(cfg.get("rounding", "none")).casefold()
    if rounding == "ceil":
        total = float(math.ceil(total))
    elif rounding == "floor":
        total = float(math.floor(total))
    elif rounding == "round":
        total = float(round(total))
    elif rounding != "none":
        raise RatingPresetError(f"Unsupported rounding mode: {rounding}")

    return RatingUtility(total=total, components=components, profile=profile_name)


def tenhou_rate_utility(profile_name: str, cfg: Mapping[str, Any], result: GameResult) -> RatingUtility:
    """Official Tenhou Rate formula for ranked games.

    Tenhou documents placement result as +30/+10/-10/-30 for 4P and
    +30/0/-30 for 3P, plus table-average-R correction and a game-count factor.
    """

    if result.self_rating is None or result.table_average_rating is None or result.games_played is None:
        raise RatingPresetError("Tenhou Rate requires self_rating, table_average_rating and games_played")

    placement_values = (
        _as_float_list(cfg.get("placement_3p", [30, 0, -30]), 3, f"{profile_name}.placement_3p")
        if result.players == 3
        else _as_float_list(cfg.get("placement_4p", [30, 10, -10, -30]), 4, f"{profile_name}.placement_4p")
    )
    result_component = placement_values[result.placement - 1]
    table_r = max(float(cfg.get("minimum_table_rating", 1500.0)), float(result.table_average_rating))
    correction = (table_r - float(result.self_rating)) / float(cfg.get("rating_divisor", 40.0))
    games = int(result.games_played)
    game_factor = 1.0 - games * 0.002 if games < 400 else 0.2
    scaling = float(cfg.get("scaling", 1.0))
    total = game_factor * (result_component + correction) * scaling
    return RatingUtility(
        total=total,
        components={"placement": result_component, "opponent_correction": correction, "game_factor": game_factor},
        profile=profile_name,
    )


def evaluate_profile(profile_name: str, cfg: Mapping[str, Any], result: GameResult) -> RatingUtility:
    kind = str(cfg.get("kind", "table")).casefold()
    if kind == "table":
        return table_utility(profile_name, cfg, result)
    if kind == "tenhou_rate":
        return tenhou_rate_utility(profile_name, cfg, result)
    raise RatingPresetError(f"Unsupported rating profile kind={kind!r} for {profile_name!r}")


class UniversalRatingMixer:
    """Samples rating objectives during training without changing Mortal ABI.

    A single Universal checkpoint learns a robust compromise over selected
    platform utilities.  A checkpoint cannot *conditionally* switch utility at
    inference because platform/rating context is intentionally absent from the
    Mortal input ABI.  Conditional specialization therefore happens by
    exporting/fine-tuning separate ABI-identical checkpoints per preset.
    """

    def __init__(self, profiles: Mapping[str, Mapping[str, Any]], weights: Mapping[str, float], seed: int = 0):
        names = list(weights)
        if not names:
            raise RatingPresetError("Universal mixer needs at least one profile")
        missing = [name for name in names if name not in profiles]
        if missing:
            raise RatingPresetError(f"Unknown profiles in universal mix: {missing}")
        vals = [float(weights[n]) for n in names]
        if any(v < 0 for v in vals) or sum(vals) <= 0:
            raise RatingPresetError("Universal profile weights must be non-negative with positive sum")
        self.profiles = profiles
        self.names = names
        self.weights = vals
        self.rng = random.Random(seed)

    def sample_profile(self) -> str:
        return self.rng.choices(self.names, weights=self.weights, k=1)[0]

    def evaluate(self, result: GameResult, profile_name: str | None = None) -> RatingUtility:
        name = profile_name or self.sample_profile()
        return evaluate_profile(name, self.profiles[name], result)


def normalized_utility(value: float, scale: float = 100.0, clip: float = 6.0) -> float:
    """Map heterogeneous platform rating points to a stable RL target range."""
    if scale <= 0:
        raise ValueError("scale must be positive")
    return max(-clip, min(clip, float(value) / scale))
