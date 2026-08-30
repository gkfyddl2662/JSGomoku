from evaluation.gating import PairedSample, bootstrap_paired_mean, build_standard_gate
from evaluation.results import parse_mjx_result, summarize_player


def test_bootstrap_detects_clear_candidate_gain():
    rows = [PairedSample(2.0 + i * 0.01, 1.0, seed=i) for i in range(40)]
    est = bootstrap_paired_mean(rows, resamples=500, seed=7)
    assert est.mean_delta > 1.0
    assert est.lower > 0.0


def test_standard_gate_passes_positive_rating_and_rank():
    utility = [PairedSample(1.0, 0.0, seed=i) for i in range(30)]
    # Average rank is lower-is-better, so candidate 1.9 beats baseline 2.1.
    rank = [PairedSample(1.9, 2.1, seed=i) for i in range(30)]
    last = [PairedSample(0.20, 0.22, seed=i) for i in range(30)]
    decision = build_standard_gate(
        rating_utility=utility,
        average_rank=rank,
        last_place_rate=last,
        resamples=300,
    )
    assert decision.passed


def test_sanma_result_summary_has_no_fourth_place():
    rows = [
        parse_mjx_result('{"game_seed":1,"rankings":{"c":1,"a":2,"b":3},"tens":{"c":40000,"a":30000,"b":20000}}'),
        parse_mjx_result('{"game_seed":2,"rankings":{"c":3,"a":1,"b":2},"tens":{"c":20000,"a":40000,"b":30000}}'),
    ]
    summary = summarize_player(rows, "c")
    assert summary["players"] == 3.0
    assert summary["place_1_rate"] == 0.5
    assert summary["place_3_rate"] == 0.5
    assert "place_4_rate" not in summary
    assert summary["last_place_rate"] == 0.5
