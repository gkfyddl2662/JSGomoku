from __future__ import annotations

from pathlib import Path

import patch_mjx_sanma_stage4 as implementation


def apply(root: Path) -> None:
    """Apply Stage 4 with the static CheckGameOver rule alias normalized.

    The Stage 4 generator keeps CheckGameOver as a static helper taking an
    explicit RuleConfig. The rest of State uses rule_.  Normalize that helper
    to a local const-reference named rule_ so generated code and invariant
    checks use one spelling without changing semantics.
    """
    original = implementation.CHECK_GAME_OVER_FUNCTION
    normalized = original.replace(
        "  const int n = rule.num_players();",
        "  const RuleConfig& rule_ = rule;\n  const int n = rule_.num_players();",
        1,
    ).replace("rule.return_points", "rule_.return_points")
    if normalized == original:
        raise RuntimeError("Stage 4 CheckGameOver normalization anchor was not found")

    implementation.CHECK_GAME_OVER_FUNCTION = normalized
    try:
        implementation.apply(root)
    finally:
        implementation.CHECK_GAME_OVER_FUNCTION = original
