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
        experimental=True,
        notes=(
            "Registered high-throughput 4P evaluator. It is not the canonical promotion backend yet; "
            "use explicitly for parity/throughput experiments under WSL2/container and promote it only "
            "after fixed-seed result/metric parity against native libriichi is demonstrated."
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
            "Experimental 3P high-throughput evaluator. Must pass libriichi3p legal-action, score and "
            "terminal-result parity before any promotion use."
        ),
    ),
    "libriichi3p": BackendCapabilities(
        name="libriichi3p",
        players=(3,),
        high_throughput=True,
        batched_agent=False,
        native_windows=True,
        experimental=False,
        notes="Canonical 3P correctness and promotion evaluator.",
    ),
    "libriichi": BackendCapabilities(
        name="libriichi",
        players=(4,),
        high_throughput=True,
        batched_agent=False,
        native_windows=True,
        experimental=False,
        notes="Canonical 4P correctness and promotion evaluator used by the current model-comparison runner.",
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
    """Select an evaluator without silently changing the canonical promotion backend."""

    if players not in (3, 4):
        raise EvaluationBackendError(f"players must be 3 or 4, got {players}")

    pref = preference.casefold()
    if pref == "auto":
        pref = "libriichi" if players == 4 else "libriichi3p"

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
            f"backend={backend.name!r} is experimental and is not the canonical promotion evaluator; "
            "set allow_experimental=True only for explicit validation/parity runs"
        )
    return backend
