from __future__ import annotations

from dataclasses import dataclass


class EvaluationBackendError(ValueError):
    pass


@dataclass(frozen=True)
class BackendCapabilities:
    name: str
    players: tuple[int, ...]
    high_throughput: bool
    batched_agent: bool
    native_windows: bool
    experimental: bool
    notes: str


BACKENDS: dict[str, BackendCapabilities] = {
    "mjx": BackendCapabilities(
        name="mjx",
        players=(4,),
        high_throughput=True,
        batched_agent=True,
        native_windows=False,
        experimental=False,
        notes=(
            "Primary 4P evaluator. Upstream is C++/Python, exposes batched Agent inference, "
            "and officially targets Linux/macOS Intel. Use WSL2/container on Windows."
        ),
    ),
    "mjx_sanma": BackendCapabilities(
        name="mjx_sanma",
        players=(3,),
        high_throughput=True,
        batched_agent=True,
        native_windows=False,
        experimental=True,
        notes=(
            "Target 3P production evaluator. Built from the pinned MJX fork/patch series. "
            "Must pass libriichi3p legal-action, score and terminal-result parity before promotion."
        ),
    ),
    "libriichi3p": BackendCapabilities(
        name="libriichi3p",
        players=(3,),
        high_throughput=True,
        batched_agent=False,
        native_windows=True,
        experimental=False,
        notes="Current 3P reference and production evaluator until MJX-Sanma parity passes.",
    ),
    "libriichi": BackendCapabilities(
        name="libriichi",
        players=(4,),
        high_throughput=True,
        batched_agent=False,
        native_windows=True,
        experimental=False,
        notes="4P correctness/reference fallback compatible with the Mortal/Akagi engine stack.",
    ),
    "mjai": BackendCapabilities(
        name="mjai",
        players=(4,),
        high_throughput=False,
        batched_agent=False,
        native_windows=False,
        experimental=False,
        notes="Legacy 4P cross-check only. Original gimite/mjai implementation is Ruby and 4P-specific.",
    ),
}


def select_backend(
    players: int,
    preference: str = "auto",
    *,
    allow_experimental: bool = False,
) -> BackendCapabilities:
    """Select an evaluator and refuse unvalidated experimental engines by default."""

    if players not in (3, 4):
        raise EvaluationBackendError(f"players must be 3 or 4, got {players}")

    pref = preference.casefold()
    if pref == "auto":
        pref = "mjx" if players == 4 else "libriichi3p"

    if pref not in BACKENDS:
        raise EvaluationBackendError(f"unknown evaluation backend: {preference!r}")

    backend = BACKENDS[pref]
    if players not in backend.players:
        supported = ", ".join(f"{p}P" for p in backend.players)
        raise EvaluationBackendError(
            f"backend={backend.name!r} does not support {players}P in this project; "
            f"supported modes: {supported}"
        )
    if backend.experimental and not allow_experimental:
        raise EvaluationBackendError(
            f"backend={backend.name!r} is experimental and has not passed its parity gate; "
            "set allow_experimental=True only for validation runs"
        )
    return backend
