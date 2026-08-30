import pytest

from evaluation.backends import EvaluationBackendError, select_backend
from evaluation.results import parse_mjx_result, summarize_player


def test_auto_backend_4p_is_mjx():
    backend = select_backend(4)
    assert backend.name == "mjx"
    assert backend.batched_agent


def test_auto_backend_3p_is_libriichi3p():
    backend = select_backend(3)
    assert backend.name == "libriichi3p"


def test_mjx_is_not_silently_used_for_sanma():
    with pytest.raises(EvaluationBackendError):
        select_backend(3, "mjx")


def test_legacy_mjai_is_not_sanma_fallback():
    with pytest.raises(EvaluationBackendError):
        select_backend(3, "mjai")


def test_mjx_result_summary():
    rows = [
        parse_mjx_result('{"gameSeed":"1","rankings":{"candidate":1},"tens":{"candidate":41000}}'),
        parse_mjx_result('{"gameSeed":"2","rankings":{"candidate":3},"tens":{"candidate":21000}}'),
    ]
    summary = summarize_player(rows, "candidate")
    assert summary["average_rank"] == 2.0
    assert summary["average_score"] == 31000.0
    assert summary["place_1_rate"] == 0.5
    assert summary["place_3_rate"] == 0.5
