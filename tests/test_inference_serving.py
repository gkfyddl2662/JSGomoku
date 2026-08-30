from __future__ import annotations

from pathlib import Path

import pytest

from serving.inference import _validate_checkpoint_config, contract_for, resolve_checkpoint_path


def test_contract_aliases() -> None:
    assert contract_for("sanma").mode == "3p"
    assert contract_for("3").action_space == 44
    assert contract_for("yonma").mode == "4p"
    assert contract_for("4").obs_channels == 1012
    with pytest.raises(ValueError):
        contract_for("5p")


def test_relative_best_state_file_resolves_under_mode_models(tmp_path: Path) -> None:
    root = tmp_path / "Mortal_Unified"
    mortal = root / "mortal"
    mortal.mkdir(parents=True)
    (mortal / "config.3p.toml").write_text(
        "[control]\nversion = 4\nbest_state_file = 'best_mortal.pth'\n",
        encoding="utf-8",
    )

    resolved = resolve_checkpoint_path(root, "3p")
    assert resolved == (root / "runtime" / "3p" / "models" / "best_mortal.pth").resolve()


def test_relative_explicit_model_resolves_under_mode_models(tmp_path: Path) -> None:
    root = tmp_path / "Mortal_Unified"
    resolved = resolve_checkpoint_path(root, "4p", Path("candidate.pth"))
    assert resolved == (root / "runtime" / "4p" / "models" / "candidate.pth").resolve()


def test_checkpoint_mode_abi_is_strict() -> None:
    cfg = {
        "control": {"version": 4},
        "resnet": {"conv_channels": 192, "num_blocks": 40},
        "game": {"mode": "3p", "num_players": 3, "action_space": 44, "obs_channels": 1010},
    }
    assert _validate_checkpoint_config(cfg, contract_for("3p")) == (192, 40)

    with pytest.raises(ValueError, match="does not match endpoint 4p"):
        _validate_checkpoint_config(cfg, contract_for("4p"))

    wrong_action = {
        **cfg,
        "game": {**cfg["game"], "action_space": 46},
    }
    with pytest.raises(ValueError, match="action-space ABI mismatch"):
        _validate_checkpoint_config(wrong_action, contract_for("3p"))


def test_checkpoint_must_remain_v4() -> None:
    cfg = {
        "control": {"version": 5},
        "resnet": {"conv_channels": 16, "num_blocks": 1},
        "game": {"mode": "3p", "num_players": 3, "action_space": 44, "obs_channels": 1010},
    }
    with pytest.raises(ValueError, match="v4 ABI only"):
        _validate_checkpoint_config(cfg, contract_for("3p"))
