from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from evaluation.paired import evaluate_promotion_records, parse_paired_record
from evaluation.strength import (
    StrengthLogError,
    pair_duplicate_logs,
    paired_records,
    paired_strength_report,
    parse_duplicate_log,
    render_strength_markdown,
)


def _profile():
    return {
        "kind": "table",
        "score_divisor": 1000.0,
        "score_weight": 0.0,
        "uma_3p": [0, 0, 0],
        "rules": [
            {
                "players": 3,
                "round": "south",
                "room": "test",
                "rank": "test",
                "placement": [10, 0, -10],
            }
        ],
    }


def _write_log(
    directory: Path,
    *,
    seed: int,
    key: int,
    split: str,
    players: int,
    start_scores: list[int],
    deltas: list[int],
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{seed}_{key}_{split}.json.gz"
    events = [
        {"type": "start_game", "names": [f"p{i}" for i in range(players)], "seed": [seed, key]},
        {
            "type": "start_kyoku",
            "bakaze": "E",
            "kyoku": 1,
            "honba": 0,
            "kyotaku": 0,
            "oya": 0,
            "scores": start_scores,
        },
        {"type": "ryukyoku", "deltas": deltas},
        {"type": "end_kyoku"},
        {"type": "end_game"},
    ]
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event, separators=(",", ":")) + "\n")
    return path


def test_paired_rating_gate_3p_passes_clear_candidate_gain():
    rows = []
    for seed in range(30):
        rows.append(
            parse_paired_record(
                '{'
                f'"seed":{seed},"seat":{seed % 3},"players":3,'
                '"starting_score":35000,"round_kind":"south","room":"test","rank":"test",'
                '"candidate":{"placement":1,"raw_score":42000},'
                '"baseline":{"placement":3,"raw_score":22000}'
                '}'
            )
        )
    decision = evaluate_promotion_records(
        rows,
        profile_name="test",
        profile=_profile(),
        resamples=300,
    )
    assert decision.passed


def test_paired_record_rejects_invalid_sanma_seat():
    try:
        parse_paired_record(
            '{"seed":1,"seat":3,"players":3,"starting_score":35000,'
            '"candidate":{"placement":1,"raw_score":40000},'
            '"baseline":{"placement":2,"raw_score":30000}}'
        )
    except ValueError as exc:
        assert "seat" in str(exc)
    else:
        raise AssertionError("invalid sanma seat must be rejected")


def test_parse_duplicate_log_uses_split_seat_and_mortal_tie_order(tmp_path: Path):
    path = _write_log(
        tmp_path,
        seed=10,
        key=99,
        split="c",
        players=3,
        start_scores=[35000, 35000, 35000],
        deltas=[5000, 5000, -10000],
    )
    result = parse_duplicate_log(path, players=3)
    assert result.seat == 2
    assert result.starting_score == 35000
    assert result.raw_score == 25000
    assert result.placement == 3
    assert not result.tobi


def test_pair_duplicate_logs_exports_promotion_records_and_strength(tmp_path: Path):
    candidate = tmp_path / "candidate"
    baseline = tmp_path / "baseline"
    seed = 20260831
    key = 0x1234

    # Same duplicate seed, all three challenger seats. Candidate wins each seat;
    # baseline finishes last in the same deterministic seat context.
    for seat, split in enumerate("abc"):
        cand_delta = [-5000, -5000, -5000]
        cand_delta[seat] = 10000
        base_delta = [5000, 5000, 5000]
        base_delta[seat] = -10000
        _write_log(
            candidate,
            seed=seed,
            key=key,
            split=split,
            players=3,
            start_scores=[35000, 35000, 35000],
            deltas=cand_delta,
        )
        _write_log(
            baseline,
            seed=seed,
            key=key,
            split=split,
            players=3,
            start_scores=[35000, 35000, 35000],
            deltas=base_delta,
        )

    rows = pair_duplicate_logs(candidate, baseline, players=3)
    assert len(rows) == 3
    assert [(row.seed, row.seed_key, row.seat) for row in rows] == [
        (seed, key, 0),
        (seed, key, 1),
        (seed, key, 2),
    ]

    records = paired_records(rows, round_kind="south", room="test", rank="test")
    assert [row["candidate"]["placement"] for row in records] == [1, 1, 1]
    assert [row["baseline"]["placement"] for row in records] == [3, 3, 3]
    assert all(row["starting_score"] == 35000 for row in records)
    assert all(row["seed_key"] == key for row in records)

    report = paired_strength_report(rows)
    assert report["candidate"]["avg_rank"] == 1.0
    assert report["baseline"]["avg_rank"] == 3.0
    assert report["candidate"]["avg_rank_pt"] == 6.0
    assert report["baseline"]["avg_rank_pt"] == -6.0
    assert report["candidate_minus_baseline"]["avg_rank"] == -2.0
    assert report["candidate_minus_baseline"]["avg_rank_pt"] == 12.0
    markdown = render_strength_markdown(report, candidate_name="ROGS", baseline_name="Mortal")
    assert "| Avg rank | 3.000000 | 1.000000 |" in markdown
    assert "| Avg rank pt | -6.000000 | 6.000000 |" in markdown


def test_pair_duplicate_logs_rejects_context_drift(tmp_path: Path):
    candidate = tmp_path / "candidate"
    baseline = tmp_path / "baseline"
    _write_log(
        candidate,
        seed=1,
        key=7,
        split="a",
        players=4,
        start_scores=[25000] * 4,
        deltas=[3000, -1000, -1000, -1000],
    )
    _write_log(
        baseline,
        seed=2,
        key=7,
        split="a",
        players=4,
        start_scores=[25000] * 4,
        deltas=[3000, -1000, -1000, -1000],
    )
    with pytest.raises(StrengthLogError, match="contexts differ"):
        pair_duplicate_logs(candidate, baseline, players=4)


def test_pair_duplicate_logs_rejects_multiple_seed_keys(tmp_path: Path):
    candidate = tmp_path / "candidate"
    baseline = tmp_path / "baseline"
    for seed, key in ((1, 7), (2, 8)):
        for root in (candidate, baseline):
            _write_log(
                root,
                seed=seed,
                key=key,
                split="a",
                players=4,
                start_scores=[25000] * 4,
                deltas=[3000, -1000, -1000, -1000],
            )
    with pytest.raises(StrengthLogError, match="one fixed duplicate seed key"):
        pair_duplicate_logs(candidate, baseline, players=4)
