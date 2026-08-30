import torch
from torch import nn

from training.mortal_hook import compute_mortal_rogs_batch, is_rogs_enabled


class TinyDQN(nn.Module):
    def __init__(self):
        super().__init__()
        self.version = 4
        self.net = nn.Linear(4, 4)  # value + 3 actions


def config():
    return {
        "control": {"version": 4},
        "rogs": {"enabled": True, "curriculum_steps": 100},
        "objective": {
            "value_weight": 1.0,
            "regret_weight": 0.5,
            "bc_anchor_weight": 0.1,
            "cql_anchor_weight": 0.25,
            "entropy_weight": 0.002,
            "regret_clip": 12.0,
        },
    }


def test_rogs_hook_keeps_dqn_parameter_shape_and_backprops():
    torch.manual_seed(1)
    dqn = TinyDQN()
    before = {k: tuple(v.shape) for k, v in dqn.state_dict().items()}
    phi = torch.randn(2, 4, requires_grad=True)
    masks = torch.tensor([[True, True, False], [False, True, True]])
    actions = torch.tensor([0, 2])
    returns = torch.tensor([1.5, -0.5])
    cql = torch.tensor(0.2, requires_grad=True)

    batch = compute_mortal_rogs_batch(
        dqn=dqn,
        phi=phi,
        masks=masks,
        actions=actions,
        returns=returns,
        cql_loss=cql,
        config=config(),
        steps=50,
    )
    batch.objective.total.backward()
    after = {k: tuple(v.shape) for k, v in dqn.state_dict().items()}

    assert before == after
    assert batch.outputs.q.shape == (2, 3)
    assert torch.isfinite(batch.objective.total)
    assert dqn.net.weight.grad is not None


def test_rogs_disabled_on_old_mortal_versions():
    cfg = config()
    cfg["control"]["version"] = 3
    assert not is_rogs_enabled(cfg, 3)
