from pathlib import Path

import pytest

from app.configuration import ConfigError, build_training_ablation_config, merge_preset
from scripts.prepare_tenhou_training import HOUOU_SHA, SANMA_SHA, YONMA_SHA, split_for


def test_merge_preset_deep_merge():
    current = {"control": {"device": "cpu", "online": False}, "env": {"gamma": 1}}
    preset = {"control": {"device": "cuda", "batch_size": 512}}
    merged = merge_preset(current, preset)
    assert merged["control"]["device"] == "cuda"
    assert merged["control"]["online"] is False
    assert merged["control"]["batch_size"] == 512
    assert merged["env"]["gamma"] == 1


def test_training_ablation_variants_are_isolated_and_non_mutating(tmp_path: Path):
    base = {
        "control": {
            "online": True,
            "state_file": "original.pth",
            "best_state_file": "original-best.pth",
            "tensorboard_dir": "original-runs",
        },
        "game": {"mode": "3p", "num_players": 3},
        "rogs": {"enabled": True},
        "global_reward": {"enabled": False, "score_delta_weight": 0.15},
        "test_play": {"log_dir": "original-test"},
        "dataset": {"globs": ["same-data/**/*.json.gz"]},
    }
    expected = {
        "mortal": (False, False),
        "rogs": (True, False),
        "rogs-global": (True, True),
    }

    configs = {}
    for variant, toggles in expected.items():
        cfg = build_training_ablation_config(
            base,
            mode="3p",
            variant=variant,
            seed=17,
            mode_root=tmp_path / "runtime" / "3p",
        )
        configs[variant] = cfg
        assert (cfg["rogs"]["enabled"], cfg["global_reward"]["enabled"]) == toggles
        assert cfg["control"]["online"] is False
        assert cfg["control"]["training_seed"] == 17
        assert cfg["dataset"]["globs"] == base["dataset"]["globs"]
        assert cfg["experiment"]["variant"] == variant
        assert cfg["experiment"]["seed"] == 17
        assert f"seed-17/{variant}" in cfg["control"]["state_file"].replace("\\", "/")
        assert f"seed-17/{variant}" in cfg["control"]["tensorboard_dir"].replace("\\", "/")

    assert len({cfg["control"]["state_file"] for cfg in configs.values()}) == 3
    assert base["control"]["online"] is True
    assert base["control"]["state_file"] == "original.pth"
    assert base["rogs"]["enabled"] is True
    assert base["global_reward"]["enabled"] is False


def test_training_ablation_rejects_mismatched_mode_and_unknown_variant(tmp_path: Path):
    base = {"game": {"mode": "4p"}}
    with pytest.raises(ConfigError, match="does not match"):
        build_training_ablation_config(
            base,
            mode="3p",
            variant="rogs",
            seed=1,
            mode_root=tmp_path,
        )
    with pytest.raises(ConfigError, match="Unknown training ablation variant"):
        build_training_ablation_config(
            {"game": {"mode": "3p"}},
            mode="3p",
            variant="mystery",
            seed=1,
            mode_root=tmp_path,
        )


def test_tenhou_train_val_split_is_deterministic_and_stable():
    samples = [f"2026-log-{i}.xml" for i in range(1000)]
    first = [split_for(name, 0.05) for name in samples]
    second = [split_for(name, 0.05) for name in samples]
    assert first == second
    assert {"train", "val"} <= set(first)
    assert 20 <= first.count("val") <= 80


def test_tenhou_preparation_pins_and_authorization_gate():
    assert HOUOU_SHA == "d4ca693771517b67172521f2bd76517500db4a6e"
    assert SANMA_SHA == "e0bd7bffe24227f97600c710cffa4490117b634a"
    assert YONMA_SHA == "c133f7dbf61046feaf1af72369d9a44056807657"

    root = Path(__file__).resolve().parents[1]
    launcher = (root / "RUN_TENHOU_FULL.bat").read_text(encoding="utf-8")
    assert "authorized" in launcher
    assert "--accept-tenhou-log-terms" in launcher
    assert "RUN_TENHOU_FULL.bat full" in launcher
