from __future__ import annotations

from pathlib import Path

import patch_mjx_sanma_stage4 as implementation


def apply(root: Path) -> None:
    """Apply Stage 4 and normalize generated C++ details.

    Stage 4 keeps CheckGameOver as a static helper taking an explicit
    RuleConfig, while the instance methods use rule_.  Normalize the static
    helper to the same local spelling so invariant checks stay simple.  Also
    fix the ron-priority lambda capture after replacing modulo-4 with the
    instance num_players() accessor.
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

    state_cpp = root / "include/mjx/internal/state.cpp"
    text = state_cpp.read_text(encoding="utf-8")
    old = "[&from_who](const mjxproto::Action &x, const mjxproto::Action &y) {\n              return ((x.who() - from_who + num_players()) % num_players()) <"
    new = "[&from_who, this](const mjxproto::Action &x, const mjxproto::Action &y) {\n              return ((x.who() - from_who + num_players()) % num_players()) <"
    if new not in text:
        if old not in text:
            raise RuntimeError("Stage 4 ron-order lambda capture anchor was not found")
        text = text.replace(old, new, 1)
        state_cpp.write_text(text, encoding="utf-8")

    if "[&from_who, this]" not in state_cpp.read_text(encoding="utf-8"):
        raise RuntimeError("Stage 4 ron-order lambda capture postcondition failed")
