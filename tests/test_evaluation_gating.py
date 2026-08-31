import json

import pytest

from evaluation.gating import PairedSample, bootstrap_paired_mean, build_standard_gate
from evaluation.paired import load_paired_records
from evaluation.results import parse_mjx_result, summarize_player


def test_bootstrap_detects_clear_candidate_gain():
    rows = [PairedSample(2.0 + i * 0.01, 1.0, seed=i) for i in range(40)]
    est = bootstrap_paired_mean(rows, resamples=500, seed=7)
    assert est.mean_delta > 1.0
    assert est.lower > 0.0
    assert est.n == 40
    assert est.clusters == 40


def test_bootstrap_resamples_duplicate_seat_rotations_by_seed_cluster():
    rows = [
        PairedSample(3.0, 0.0, seed=10, group="10:0"),
        PairedSample(2.0, 0.0, seed=10, group="10:1"),
        PairedSample(1.0, 0.0, seed=10, group="10:2"),
        PairedSample(-1.0, 0.0, seed=11, group="11:0"),
        PairedSample(-2.0, 0.0, seed=11, group="11:1"),
        PairedSample(-3.0, 0.0, seed=11, group="11:2"),
    ]
    est = bootstrap_paired_mean(rows, resamples=500, seed=19)
    assert est.n == 6
    assert est.clusters == 2
    assert est.mean_delta == pytest.approx(0.0)


def test_paired_loader_rejects_incomplete_seed_rotation(tmp_path):
    path = tmp_path / "paired.jsonl"
    base = {
        "seed": 100,
        "players": 3,
        "starting_score": 35000,
        "round_kind": "south",
        "room": "*",
        "rank": "*",
        "candidate": {"placement": 1, "raw_score": 40000},
        "baseline": {"placement": 2, "raw_score": 35000},
    }
    rows = []
    for seat in (0, 1):
        row = dict(base)
        row["seat"] = seat
        rows.append(json.dumps(row))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="complete seat rotation"):
        load_paired_records(path)


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
