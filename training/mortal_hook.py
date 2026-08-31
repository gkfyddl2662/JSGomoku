from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import torch
from torch import Tensor, nn
from torch.nn import functional as F

from .objective import ROGSObjectiveResult, ROGSWeights, compose_rogs_objective, curriculum_weights
from .rogs import MortalV4Outputs, mortal_v4_outputs, sampled_advantage_target


@dataclass(frozen=True)
class MortalROGSBatch:
    outputs: MortalV4Outputs
    chosen_q: Tensor
    objective: ROGSObjectiveResult
    regret_target: Tensor
    regret_target_raw: Tensor
    legal_action_count: Tensor
    oracle_available: bool
    search_available: bool


def is_rogs_enabled(config: Mapping[str, Any], version: int) -> bool:
    # v4 is the canonical Mortal compatibility backend. A research-only custom
    # version may call the same objective helper, but AkagiOT itself does not
    # require a Mortal checkpoint version; that is a backend/export concern.
    return bool(config.get("rogs", {}).get("enabled", False)) and version in (4, 5)


def _base_weights(config: Mapping[str, Any]) -> ROGSWeights:
    obj = config.get("objective", {})
    return ROGSWeights(
        value=float(obj.get("value_weight", 1.0)),
        regret=float(obj.get("regret_weight", 0.5)),
        oracle=float(obj.get("oracle_weight", obj.get("teacher_kl_weight", 0.3))),
        search=float(obj.get("search_weight", obj.get("teacher_kl_weight", 0.3))),
        behavior_cloning=float(obj.get("bc_anchor_weight", 0.1)),
        cql=float(obj.get("cql_anchor_weight", 0.25)),
        entropy=float(obj.get("entropy_weight", 0.002)),
    )


def _progress(config: Mapping[str, Any], steps: int) -> float:
    rogs = config.get("rogs", {})
    total = int(rogs.get("curriculum_steps", 1_000_000))
    if total <= 0:
        return 1.0
    return max(0.0, min(1.0, float(steps) / float(total)))


def compute_mortal_rogs_batch(
    *,
    dqn: nn.Module,
    phi: Tensor,
    masks: Tensor,
    actions: Tensor,
    returns: Tensor,
    cql_loss: Tensor | None,
    config: Mapping[str, Any],
    steps: int,
    enable_behavior_cloning: bool = True,
    oracle_q: Tensor | None = None,
    search_q: Tensor | None = None,
) -> MortalROGSBatch:
    """Build the ROGS scalar loss from a Mortal-compatible dueling DQN head."""

    version = int(config.get("control", {}).get("version", getattr(dqn, "version", 0)))
    if not is_rogs_enabled(config, version):
        raise RuntimeError("ROGS hook was called while disabled or on an unsupported DQN version")

    outputs = mortal_v4_outputs(dqn, phi, masks)
    chosen_q = outputs.q.gather(-1, actions.long().unsqueeze(-1)).squeeze(-1)
    regret_clip = float(config.get("objective", {}).get("regret_clip", 12.0))
    regret_target_raw = sampled_advantage_target(
        returns,
        outputs.value,
        clip=None,
    )
    regret_target = regret_target_raw.clamp(-regret_clip, regret_clip)

    # Logged expert actions can anchor offline training. Online self-play should
    # normally disable this term so it does not merely imitate its own samples.
    bc_loss = F.cross_entropy(outputs.q, actions.long()) if enable_behavior_cloning else None

    base = _base_weights(config)
    weights = curriculum_weights(
        _progress(config, steps),
        base=base,
        oracle_final=float(config.get("rogs", {}).get("oracle_final_weight", 0.05)),
        bc_final=float(config.get("rogs", {}).get("bc_final_weight", 0.02)),
        cql_final=float(config.get("rogs", {}).get("cql_final_weight", 0.05)),
        regret_final=float(config.get("rogs", {}).get("regret_final_weight", 0.75)),
    )
    if not enable_behavior_cloning:
        weights = ROGSWeights(
            value=weights.value,
            regret=weights.regret,
            oracle=weights.oracle,
            search=weights.search,
            behavior_cloning=0.0,
            cql=weights.cql,
            entropy=weights.entropy,
        )

    result = compose_rogs_objective(
        value_pred=outputs.value,
        value_target=returns,
        advantage=outputs.advantage,
        action_index=actions,
        regret_target=regret_target,
        legal_mask=masks,
        student_q=outputs.q,
        oracle_q=oracle_q,
        search_q=search_q,
        behavior_cloning_loss=bc_loss,
        cql_loss=cql_loss,
        weights=weights,
        teacher_temperature=float(config.get("objective", {}).get("teacher_temperature", 1.5)),
        regret_clip=regret_clip,
    )

    if not torch.isfinite(chosen_q).all():
        raise FloatingPointError("Chosen action contains a non-finite Q value")
    return MortalROGSBatch(
        outputs=outputs,
        chosen_q=chosen_q,
        objective=result,
        regret_target=regret_target,
        regret_target_raw=regret_target_raw,
        legal_action_count=masks.to(torch.bool).sum(dim=-1),
        oracle_available=oracle_q is not None,
        search_available=search_q is not None,
    )
