import pytest

from evaluation.backends import EvaluationBackendError, select_backend
from evaluation.results import parse_mjx_result, summarize_player


def test_auto_backend_4p_is_native_libriichi_until_mjx_parity_is_promoted():
    backend = select_backend(4)
    assert backend.name == "libriichi"
    assert backend.native_windows
    assert not backend.experimental


def test_auto_backend_3p_is_libriichi3p_until_parity_passes():
    backend = select_backend(3)
    assert backend.name == "libriichi3p"


def test_mjx_4p_requires_explicit_experimental_opt_in():
    with pytest.raises(EvaluationBackendError):
        select_backend(4, "mjx")
    backend = select_backend(4, "mjx", allow_experimental=True)
    assert backend.experimental
    assert backend.batched_agent


def test_upstream_mjx_is_not_silently_used_for_sanma():
    with pytest.raises(EvaluationBackendError):
        select_backend(3, "mjx")


def test_mjx_sanma_requires_explicit_experimental_opt_in():
    with pytest.raises(EvaluationBackendError):
        select_backend(3, "mjx_sanma")
    backend = select_backend(3, "mjx_sanma", allow_experimental=True)
    assert backend.experimental
    assert backend.batched_agent


def test_legacy_mjai_is_not_sanma_fallback():
    with pytest.raises(EvaluationBackendError):
        select_backend(3, "mjai")


def test_mjx_result_summary_4p():
    rows = [
        parse_mjx_result('{"gameSeed":"1","rankings":{"candidate":1,"a":2,"b":3,"c":4},"tens":{"candidate":41000,"a":25000,"b":20000,"c":14000}}'),
        parse_mjx_result('{"gameSeed":"2","rankings":{"candidate":3,"a":1,"b":2,"c":4},"tens":{"candidate":21000,"a":39000,"b":26000,"c":14000}}'),
    ]
    summary = summarize_player(rows, "candidate")
    assert summary["average_rank"] == 2.0
    assert summary["average_score"] == 31000.0
    assert summary["place_1_rate"] == 0.5
    assert summary["place_3_rate"] == 0.5
    assert summary["place_4_rate"] == 0.0
