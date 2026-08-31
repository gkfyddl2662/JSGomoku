from __future__ import annotations

from dataclasses import dataclass
import math
import random
from statistics import mean
from typing import Iterable, Sequence


@dataclass(frozen=True)
class PairedSample:
    """Matched candidate/baseline observation from the same game context."""

    candidate: float
    baseline: float
    seed: int | None = None
    group: str = ""

    @property
    def delta(self) -> float:
        return float(self.candidate) - float(self.baseline)


@dataclass(frozen=True)
class BootstrapEstimate:
    n: int
    mean_delta: float
    lower: float
    upper: float
    confidence: float
    clusters: int = 0


@dataclass(frozen=True)
class GateMetric:
    name: str
    estimate: BootstrapEstimate
    min_mean: float = 0.0
    min_lower: float | None = None
    required: bool = True

    @property
    def passed(self) -> bool:
        if self.estimate.mean_delta < self.min_mean:
            return False
        return self.min_lower is None or self.estimate.lower >= self.min_lower


@dataclass(frozen=True)
class PromotionDecision:
    passed: bool
    metrics: tuple[GateMetric, ...]
    reason: str


def _percentile(sorted_values: Sequence[float], q: float) -> float:
    if not sorted_values:
        raise ValueError("Cannot compute percentile of an empty sequence")
    if q <= 0:
        return float(sorted_values[0])
    if q >= 1:
        return float(sorted_values[-1])
    pos = (len(sorted_values) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return float(sorted_values[lo])
    w = pos - lo
    return float(sorted_values[lo] * (1.0 - w) + sorted_values[hi] * w)


def _cluster_deltas(rows: Sequence[PairedSample]) -> tuple[tuple[float, ...], ...]:
    """Group duplicate-evaluation rows by game seed.

    Seat rotations generated from the same duplicate seed share the same wall and
    game context and therefore are not independent observations. Rows without a
    seed keep backward-compatible iid behavior by becoming one-row clusters.
    """

    grouped: dict[tuple[str, int], list[float]] = {}
    for idx, row in enumerate(rows):
        key = ("seed", int(row.seed)) if row.seed is not None else ("row", idx)
        grouped.setdefault(key, []).append(row.delta)
    return tuple(tuple(values) for values in grouped.values())


def bootstrap_paired_mean(
    samples: Iterable[PairedSample],
    *,
    resamples: int = 5000,
    confidence: float = 0.95,
    seed: int = 0,
) -> BootstrapEstimate:
    """Paired cluster bootstrap over candidate-baseline deltas.

    Duplicate seat rotations with the same ``PairedSample.seed`` are resampled
    together. This preserves the correlation structure of A/B/C(/D) duplicate
    games instead of treating every seat rotation as an iid game. Samples with
    no seed remain one-row clusters for generic callers.
    """

    rows = tuple(samples)
    if not rows:
        raise ValueError("At least one paired sample is required")
    if resamples < 100:
        raise ValueError("resamples must be >= 100")
    if not 0.5 < confidence < 1.0:
        raise ValueError("confidence must be in (0.5, 1.0)")

    deltas = tuple(row.delta for row in rows)
    clusters = _cluster_deltas(rows)
    cluster_count = len(clusters)
    rng = random.Random(seed)

    boot: list[float] = []
    for _ in range(resamples):
        sampled_total = 0.0
        sampled_n = 0
        for _ in range(cluster_count):
            cluster = clusters[rng.randrange(cluster_count)]
            sampled_total += sum(cluster)
            sampled_n += len(cluster)
        boot.append(sampled_total / sampled_n)

    boot.sort()
    alpha = (1.0 - confidence) / 2.0
    return BootstrapEstimate(
        n=len(deltas),
        mean_delta=mean(deltas),
        lower=_percentile(boot, alpha),
        upper=_percentile(boot, 1.0 - alpha),
        confidence=confidence,
        clusters=cluster_count,
    )


def decide_promotion(metrics: Iterable[GateMetric]) -> PromotionDecision:
    rows = tuple(metrics)
    if not rows:
        raise ValueError("At least one gate metric is required")
    failed = [m for m in rows if m.required and not m.passed]
    if failed:
        detail = ", ".join(
            f"{m.name}: mean={m.estimate.mean_delta:.6f}, "
            f"CI=[{m.estimate.lower:.6f},{m.estimate.upper:.6f}]"
            for m in failed
        )
        return PromotionDecision(False, rows, f"Required gate failed: {detail}")
    return PromotionDecision(True, rows, "All required promotion gates passed")


def _flip_lower_is_better(samples: Iterable[PairedSample]) -> list[PairedSample]:
    return [PairedSample(-x.candidate, -x.baseline, x.seed, x.group) for x in samples]


def build_standard_gate(
    *,
    rating_utility: Iterable[PairedSample],
    average_rank: Iterable[PairedSample] | None = None,
    last_place_rate: Iterable[PairedSample] | None = None,
    resamples: int = 5000,
    confidence: float = 0.95,
    min_rating_mean: float = 0.0,
    min_rating_lower: float = 0.0,
    min_rank_improvement: float = 0.0,
    max_last_place_regression: float = 0.0,
    seed: int = 0,
) -> PromotionDecision:
    """Default ROGS gate. Positive deltas always mean candidate improvement."""

    metrics: list[GateMetric] = []
    rating_est = bootstrap_paired_mean(
        rating_utility, resamples=resamples, confidence=confidence, seed=seed
    )
    metrics.append(
        GateMetric(
            "rating_utility",
            rating_est,
            min_mean=min_rating_mean,
            min_lower=min_rating_lower,
            required=True,
        )
    )

    if average_rank is not None:
        rank_est = bootstrap_paired_mean(
            _flip_lower_is_better(average_rank),
            resamples=resamples,
            confidence=confidence,
            seed=seed + 1,
        )
        metrics.append(
            GateMetric(
                "average_rank_improvement",
                rank_est,
                min_mean=min_rank_improvement,
                required=True,
            )
        )

    if last_place_rate is not None:
        last_est = bootstrap_paired_mean(
            _flip_lower_is_better(last_place_rate),
            resamples=resamples,
            confidence=confidence,
            seed=seed + 2,
        )
        metrics.append(
            GateMetric(
                "last_place_non_regression",
                last_est,
                min_mean=-max_last_place_regression,
                required=True,
            )
        )

    return decide_promotion(metrics)
