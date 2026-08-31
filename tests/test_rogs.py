import torch
from torch import nn

from training.rogs import (
    hedge_policy,
    masked_teacher_kl,
    mortal_v4_outputs,
    potential_shaped_reward,
    regret_regression_loss,
    sampled_advantage_target,
)


class FakeV4DQN(nn.Module):
    def __init__(self, action_space: int):
        super().__init__()
        self.net = nn.Linear(4, 1 + action_space, bias=False)


def test_mortal_v4_decomposition_preserves_argmax():
    torch.manual_seed(7)
    dqn = FakeV4DQN(3)
    phi = torch.randn(5, 4)
    mask = torch.tensor([[1, 1, 1], [1, 0, 1], [0, 1, 1], [1, 1, 0], [1, 1, 1]], dtype=torch.bool)
    out = mortal_v4_outputs(dqn, phi, mask)
    assert out.q.shape == (5, 3)
    assert torch.equal(out.q.argmax(-1), out.advantage.masked_fill(~mask, -torch.inf).argmax(-1))


def test_hedge_policy_masks_illegal_actions():
    adv = torch.tensor([[1.0, 2.0, 9.0]])
    mask = torch.tensor([[True, True, False]])
    p = hedge_policy(adv, mask, eta=0.5)
    assert torch.allclose(p.sum(-1), torch.ones(1))
    assert p[0, 2].item() == 0.0
    assert p[0, 1] > p[0, 0]


def test_identical_teacher_has_near_zero_kl():
    scores = torch.tensor([[0.1, 0.4, -0.2], [1.0, -0.5, 0.3]])
    mask = torch.tensor([[True, True, False], [True, True, True]])
    loss = masked_teacher_kl(scores, scores, mask, temperature=1.5)
    assert abs(loss.item()) < 1e-6


def test_regret_target_and_loss_are_finite():
    value = torch.tensor([[1.0], [0.5]])
    returns = torch.tensor([3.0, -2.0])
    target = sampled_advantage_target(returns, value)
    adv = torch.tensor([[0.1, 0.2], [-0.4, 0.3]])
    actions = torch.tensor([1, 0])
    loss = regret_regression_loss(adv, actions, target)
    assert torch.isfinite(loss)


def test_potential_shaping():
    base = torch.tensor([1.0])
    prev = torch.tensor([2.0])
    nxt = torch.tensor([4.0])
    assert torch.allclose(potential_shaped_reward(base, prev, nxt), torch.tensor([3.0]))
