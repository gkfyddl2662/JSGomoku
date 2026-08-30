from __future__ import annotations

import pytest

from training.game_mode import game_mode_spec, normalize_mode


def test_mode_aliases() -> None:
    assert normalize_mode("sanma") == "3p"
    assert normalize_mode("3") == "3p"
    assert normalize_mode("yonma") == "4p"
    assert normalize_mode("4") == "4p"
    with pytest.raises(ValueError):
        normalize_mode("5p")


def test_sanma_contract() -> None:
    spec = game_mode_spec("3p")
    assert spec.players == 3
    assert spec.action_space == 44
    assert spec.obs_shape_v4 == (1010, 34)
    assert spec.oracle_obs_shape_v4 == (217, 34)
    assert spec.grp_size == 6
    assert spec.allow_chi is False
    assert spec.allow_nuki is True
    assert spec.checkpoint_name == "mortal3p.pth"


def test_yonma_contract() -> None:
    spec = game_mode_spec("4p")
    assert spec.players == 4
    assert spec.action_space == 46
    assert spec.obs_shape_v4 == (1012, 34)
    assert spec.oracle_obs_shape_v4 == (217, 34)
    assert spec.grp_size == 7
    assert spec.allow_chi is True
    assert spec.allow_nuki is False
    assert spec.checkpoint_name == "mortal.pth"


def test_modes_share_deployment_version_contract() -> None:
    # The unified core intentionally keeps both deployment families on Mortal v4.
    # Their observation/action shapes differ, so checkpoints stay mode-specific.
    assert game_mode_spec("3p").action_space != game_mode_spec("4p").action_space
    assert game_mode_spec("3p").obs_shape_v4 != game_mode_spec("4p").obs_shape_v4
