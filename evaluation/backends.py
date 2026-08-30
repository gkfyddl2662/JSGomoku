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
    notes: str


BACKENDS: dict[str, BackendCapabilities] = {
    "mjx": BackendCapabilities(
        name="mjx",
        players=(4,),
        high_throughput=True,
        batched_agent=True,
        native_windows=False,
        notes=(
            "Primary 4P evaluator. Upstream is C++/Python, exposes batched Agent inference, "
            "and officially targets Linux/macOS Intel. Use WSL2/container on Windows."
        ),
    ),
    "libriichi3p": BackendCapabilities(
        name="libriichi3p",
        players=(3,),
        high_throughput=True,
        batched_agent=False,
        native_windows=True,
        notes="Primary 3P evaluator because upstream MJX and gimite/mjai are 4P-oriented.",
    ),
    "libriichi": BackendCapabilities(
        name="libriichi",
        players=(4,),
        high_throughput=True,
        batched_agent=False,
        native_windows=True,
        notes="4P correctness/reference fallback compatible with the Mortal/Akagi engine stack.",
    ),
    "mjai": BackendCapabilities(
        name="mjai",
        players=(4,),
        high_throughput=False,
        batched_agent=False,
        native_windows=False,
        notes="Legacy 4P cross-check only. Original gimite/mjai implementation is Ruby and 4P-specific.",
    ),
}


def select_backend(players: int, preference: str = "auto") -> BackendCapabilities:
    """Select the evaluator without pretending unsupported player counts work.

    Policy:
      * 4P -> MJX by default.
      * 3P -> Akagi-compatible libriichi3p.
      * gimite/mjai is never silently selected for 3P because its game loop is
        also hard-coded around four seats.
    """

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
    return backend
