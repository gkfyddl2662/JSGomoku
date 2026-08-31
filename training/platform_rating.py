from __future__ import annotations

from typing import Any, Mapping, Sequence

from .rating import GameResult, RatingPresetError, RatingUtility, evaluate_profile


def _values(value: Any, n: int, name: str) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise RatingPresetError(f"{name} must be a sequence")
    out = [float(x) for x in value]
    if len(out) != n:
        raise RatingPresetError(f"{name} must have {n} values")
    return out


def _matches(rule: Mapping[str, Any], result: GameResult) -> bool:
    actual = {
        "players": result.players,
        "round": result.round_kind,
        "room": result.room,
        "rank": result.rank,
    }
    for key, value in actual.items():
        expected = rule.get(key, "*")
        if expected == "*":
            continue
        if key == "players":
            if int(expected) != int(value):
                return False
        elif str(expected).casefold() != str(value).casefold():
            return False
    return True


def _pick(rules: Sequence[Mapping[str, Any]], result: GameResult, name: str) -> Mapping[str, Any]:
    found = []
    for idx, rule in enumerate(rules):
        if _matches(rule, result):
            specificity = sum(rule.get(k, "*") != "*" for k in ("players", "round", "room", "rank"))
            found.append((specificity, idx, rule))
    if not found:
        raise RatingPresetError(
            f"No {name} matches players={result.players}, round={result.round_kind}, "
            f"room={result.room}, rank={result.rank}; refusing to guess rating rules"
        )
    return max(found, key=lambda row: (row[0], row[1]))[2]


def decomposed_platform_utility(profile_name: str, cfg: Mapping[str, Any], result: GameResult) -> RatingUtility:
    """score + uma + room-dependent term + rank-dependent term."""
    room_rule = _pick(cfg.get("room_rules", []), result, f"{profile_name}.room_rules")
    rank_rule = _pick(cfg.get("rank_rules", []), result, f"{profile_name}.rank_rules")
    idx = result.placement - 1

    room = _values(room_rule["placement"], result.players, "room placement")[idx]
    rank = _values(rank_rule["placement"], result.players, "rank placement")[idx]
    uma_key = "uma_3p" if result.players == 3 else "uma_4p"
    uma = _values(cfg.get(uma_key, [0] * result.players), result.players, uma_key)[idx]

    divisor = float(cfg.get("score_divisor", 0.0))
    score = 0.0 if divisor <= 0 else (result.raw_score - result.starting_score) / divisor
    total = score * float(cfg.get("score_weight", 1.0)) + uma + room + rank
    return RatingUtility(
        total=total,
        components={"score": score, "uma": uma, "room": room, "rank": rank},
        profile=profile_name,
    )


def tenhou_dan_utility(profile_name: str, cfg: Mapping[str, Any], result: GameResult) -> RatingUtility:
    """Official Tenhou dan-point shape for 1dan..10dan, 3P and 4P."""
    try:
        dan = int(result.rank.casefold().removesuffix("dan"))
    except ValueError as exc:
        raise RatingPresetError("Tenhou dan rank must look like '6dan'") from exc
    if not 1 <= dan <= 10:
        raise RatingPresetError("Tenhou dan utility currently covers 1dan..10dan")

    room = result.room.casefold()
    table_4p = {
        "general": (20.0, 10.0),
        "upper": (40.0, 10.0),
        "tokujou": (50.0, 20.0),
        "houou": (60.0, 30.0),
    }
    table_3p = {
        "general": (30.0, 0.0),
        "upper": (50.0, 0.0),
        "tokujou": (70.0, 0.0),
        "houou": (90.0, 0.0),
    }
    table = table_3p if result.players == 3 else table_4p
    if room not in table:
        raise RatingPresetError(f"Unknown Tenhou room {result.room!r}")

    first, second = table[room]
    last = -(dan * 10.0 + 20.0)
    placements = [first, second, last] if result.players == 3 else [first, second, 0.0, last]
    factor = 1.5 if result.round_kind.casefold() == "south" else 1.0
    value = placements[result.placement - 1] * factor
    return RatingUtility(total=value, components={"dan_points": value}, profile=profile_name)


def evaluate_platform_profile(profile_name: str, cfg: Mapping[str, Any], result: GameResult) -> RatingUtility:
    kind = str(cfg.get("kind", "table")).casefold()
    if kind == "decomposed_table":
        return decomposed_platform_utility(profile_name, cfg, result)
    if kind == "tenhou_dan":
        return tenhou_dan_utility(profile_name, cfg, result)
    return evaluate_profile(profile_name, cfg, result)
