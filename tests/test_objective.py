import torch

from training.objective import ROGSWeights, compose_rogs_objective, curriculum_weights


def test_curriculum_moves_from_teacher_to_regret():
    early = curriculum_weights(0.0)
    late = curriculum_weights(1.0)
    assert late.regret > early.regret
    assert late.oracle < early.oracle
    assert late.behavior_cloning < early.behavior_cloning
    assert late.cql < early.cql


def test_objective_is_finite_with_masked_teacher_logits():
    value_pred = torch.tensor([0.2, -0.1], requires_grad=True)
    value_target = torch.tensor([1.0, -1.0])
    advantage = torch.tensor([[0.2, 0.0, -0.1], [0.1, -0.2, 0.0]], requires_grad=True)
    action_index = torch.tensor([0, 1])
    regret_target = torch.tensor([0.8, -0.4])
    legal = torch.tensor([[True, True, False], [True, True, False]])
    student_q = torch.tensor([[1.0, 0.5, -9.0], [0.4, 0.8, -9.0]], requires_grad=True)
    teacher_q = torch.tensor([[1.2, 0.2, -99.0], [0.3, 1.0, -99.0]])

    result = compose_rogs_objective(
        value_pred=value_pred,
        value_target=value_target,
        advantage=advantage,
        action_index=action_index,
        regret_target=regret_target,
        legal_mask=legal,
        student_q=student_q,
        oracle_q=teacher_q,
        search_q=teacher_q,
        behavior_cloning_loss=torch.tensor(0.3),
        cql_loss=torch.tensor(0.2),
        weights=ROGSWeights(),
    )
    assert torch.isfinite(result.total)
    result.total.backward()
    assert value_pred.grad is not None
    assert advantage.grad is not None
    assert student_q.grad is not None
