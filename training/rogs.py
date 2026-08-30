from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import Tensor, nn
from torch.nn import functional as F


@dataclass(frozen=True)
class MortalV4Outputs:
    """Parameter-free view of a Mortal v4 DQN output.

    Mortal v4 stores a single Linear(1024, 1 + ACTION_SPACE) layer.  We expose
    the value and centred advantage terms without adding any deploy-time
    parameters, so the resulting state_dict remains fully compatible with
    standard Mortal/Akagi-NG loaders.
    """

    value: Tensor
    advantage: Tensor
    q: Tensor


def mortal_v4_outputs(dqn: nn.Module, phi: Tensor, mask: Tensor) -> MortalV4Outputs:
    if not hasattr(dqn, "net"):
        raise TypeError("ROGS requires a Mortal v4 DQN exposing dqn.net")
    if mask.dtype is not torch.bool:
        mask = mask.to(torch.bool)

    action_space = mask.shape[-1]
    raw = dqn.net(phi)
    if raw.shape[-1] != action_space + 1:
        raise ValueError(f"Expected 1+{action_space} outputs, got {raw.shape[-1]}")

    value, action_raw = raw.split((1, action_space), dim=-1)
    valid_count = mask.sum(-1, keepdim=True).clamp_min(1)
    masked_sum = action_raw.masked_fill(~mask, 0.0).sum(-1, keepdim=True)
    centred_advantage = action_raw - masked_sum / valid_count
    q = (value + centred_advantage).masked_fill(~mask, -torch.inf)
    return MortalV4Outputs(value=value, advantage=centred_advantage, q=q)


def hedge_policy(advantage: Tensor, mask: Tensor, eta: float = 1.0) -> Tensor:
    """Convert neural cumulative-advantage/regret estimates into a Hedge policy."""
    if eta <= 0:
        raise ValueError("eta must be positive")
    if mask.dtype is not torch.bool:
        mask = mask.to(torch.bool)
    logits = (advantage * eta).masked_fill(~mask, -torch.inf)
    return torch.softmax(logits, dim=-1)


def sampled_advantage_target(
    returns: Tensor,
    value: Tensor,
    *,
    clip: float | None = 12.0,
    detach_baseline: bool = True,
) -> Tensor:
    """Low-variance sampled advantage used as a regret-like target.

    This follows the ACH/LuckyJ direction conceptually: policy preference is
    trained from sampled advantage rather than directly maximizing raw return.
    For three-player sanma this is an optimization heuristic; the two-player
    zero-sum Nash-convergence guarantee of ACH does not carry over.
    """
    baseline = value.detach() if detach_baseline else value
    target = returns - baseline.squeeze(-1)
    if clip is not None:
        target = target.clamp(-clip, clip)
    return target


def regret_regression_loss(
    advantage: Tensor,
    actions: Tensor,
    regret_target: Tensor,
    *,
    sample_weight: Tensor | None = None,
    huber_delta: float = 1.0,
) -> Tensor:
    chosen = advantage.gather(-1, actions.long().unsqueeze(-1)).squeeze(-1)
    loss = F.huber_loss(chosen, regret_target, reduction="none", delta=huber_delta)
    if sample_weight is not None:
        weight = sample_weight.to(loss.dtype)
        return (loss * weight).sum() / weight.sum().clamp_min(1e-8)
    return loss.mean()


def value_loss(value: Tensor, returns: Tensor, *, huber_delta: float = 1.0) -> Tensor:
    return F.huber_loss(value.squeeze(-1), returns, delta=huber_delta)


def masked_teacher_kl(
    student_scores: Tensor,
    teacher_scores: Tensor,
    mask: Tensor,
    *,
    temperature: float = 1.0,
) -> Tensor:
    """Distil oracle/search teacher preferences without changing inference ABI."""
    if temperature <= 0:
        raise ValueError("temperature must be positive")
    if mask.dtype is not torch.bool:
        mask = mask.to(torch.bool)

    s = (student_scores / temperature).masked_fill(~mask, -torch.inf)
    t = (teacher_scores / temperature).masked_fill(~mask, -torch.inf)
    teacher_prob = torch.softmax(t, dim=-1)
    student_log_prob = torch.log_softmax(s, dim=-1)
    return F.kl_div(student_log_prob, teacher_prob, reduction="batchmean") * (temperature**2)


def entropy_bonus(policy: Tensor, mask: Tensor) -> Tensor:
    if mask.dtype is not torch.bool:
        mask = mask.to(torch.bool)
    p = policy.masked_fill(~mask, 0.0).clamp_min(1e-12)
    entropy = -(p * p.log()).sum(-1)
    return entropy.mean()


def potential_shaped_reward(
    base_reward: Tensor,
    potential_prev: Tensor,
    potential_next: Tensor,
    *,
    gamma: float = 1.0,
) -> Tensor:
    """Suphx-style global-reward-predictor potential shaping."""
    return base_reward + gamma * potential_next - potential_prev
