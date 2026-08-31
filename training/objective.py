from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import torch
from torch import Tensor

from .rogs import entropy_bonus, masked_teacher_kl, regret_regression_loss, value_loss


@dataclass(frozen=True)
class ROGSWeights:
    value: float = 1.0
    regret: float = 0.5
    oracle: float = 0.3
    search: float = 0.3
    behavior_cloning: float = 0.1
    cql: float = 0.25
    entropy: float = 0.002


@dataclass(frozen=True)
class ROGSObjectiveResult:
    total: Tensor
    components: Mapping[str, Tensor]
    weights: ROGSWeights


def linear_decay(start: float, final: float, progress: float) -> float:
    p = max(0.0, min(1.0, float(progress)))
    return float(start) + (float(final) - float(start)) * p


def curriculum_weights(
    progress: float,
    *,
    base: ROGSWeights = ROGSWeights(),
    oracle_final: float = 0.05,
    bc_final: float = 0.02,
    cql_final: float = 0.05,
    regret_final: float = 0.75,
) -> ROGSWeights:
    """Warm-start from logged play, then hand control to self-play/regret."""

    return ROGSWeights(
        value=base.value,
        regret=linear_decay(base.regret, regret_final, progress),
        oracle=linear_decay(base.oracle, oracle_final, progress),
        search=base.search,
        behavior_cloning=linear_decay(base.behavior_cloning, bc_final, progress),
        cql=linear_decay(base.cql, cql_final, progress),
        entropy=base.entropy,
    )


def compose_rogs_objective(
    *,
    value_pred: Tensor,
    value_target: Tensor,
    advantage: Tensor,
    action_index: Tensor,
    regret_target: Tensor,
    legal_mask: Tensor,
    student_q: Tensor,
    weights: ROGSWeights,
    oracle_q: Tensor | None = None,
    search_q: Tensor | None = None,
    behavior_cloning_loss: Tensor | None = None,
    cql_loss: Tensor | None = None,
    teacher_temperature: float = 1.5,
    regret_clip: float | None = 12.0,
) -> ROGSObjectiveResult:
    """Compose one optimizer-ready scalar without changing Mortal parameters."""

    if legal_mask.dtype != torch.bool:
        legal_mask = legal_mask.to(torch.bool)
    if not legal_mask.any(dim=-1).all():
        raise ValueError("Every ROGS sample must have at least one legal action")

    components: dict[str, Tensor] = {}
    components["value"] = value_loss(value_pred, value_target)
    target = regret_target
    if regret_clip is not None:
        target = target.clamp(-float(regret_clip), float(regret_clip))
    components["regret"] = regret_regression_loss(
        advantage,
        action_index,
        target,
    )

    if oracle_q is not None and weights.oracle != 0:
        components["oracle"] = masked_teacher_kl(
            student_q,
            oracle_q,
            legal_mask,
            temperature=teacher_temperature,
        )
    if search_q is not None and weights.search != 0:
        components["search"] = masked_teacher_kl(
            student_q,
            search_q,
            legal_mask,
            temperature=teacher_temperature,
        )
    if behavior_cloning_loss is not None and weights.behavior_cloning != 0:
        components["behavior_cloning"] = behavior_cloning_loss
    if cql_loss is not None and weights.cql != 0:
        components["cql"] = cql_loss

    # Entropy expects a probability distribution, never raw Q values. Illegal
    # actions stay exactly zero after masking to avoid NaNs from -inf logits.
    policy_logits = student_q.masked_fill(~legal_mask, -torch.inf)
    policy = torch.softmax(policy_logits, dim=-1)
    components["entropy"] = entropy_bonus(policy, legal_mask)

    total = components["value"] * weights.value
    total = total + components["regret"] * weights.regret
    if "oracle" in components:
        total = total + components["oracle"] * weights.oracle
    if "search" in components:
        total = total + components["search"] * weights.search
    if "behavior_cloning" in components:
        total = total + components["behavior_cloning"] * weights.behavior_cloning
    if "cql" in components:
        total = total + components["cql"] * weights.cql
    total = total - components["entropy"] * weights.entropy

    if not torch.isfinite(total):
        raise FloatingPointError("Non-finite ROGS objective")
    return ROGSObjectiveResult(total=total, components=components, weights=weights)
