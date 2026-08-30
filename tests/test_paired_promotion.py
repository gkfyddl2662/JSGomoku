from evaluation.paired import evaluate_promotion_records, parse_paired_record


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
