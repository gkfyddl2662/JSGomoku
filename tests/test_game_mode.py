from __future__ import annotations

from pathlib import Path

import pytest

from scripts.generate_population_selfplay import (
    GENERATION_STATE_PROTOCOL,
    load_generation_state,
    matchup_order,
    save_generation_state,
)
from scripts.prepare_selfplay_population import build_matchup_order, choose_champion
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


def test_selfplay_population_single_member_uses_mirror_match() -> None:
    assert build_matchup_order(["only"], "only") == [("only", "only")]


def test_selfplay_population_prioritizes_champion_crossplay() -> None:
    order = build_matchup_order(["champ", "other"], "champ")
    assert order[:2] == [("other", "champ"), ("champ", "other")]
    assert ("champ", "champ") in order


def test_selfplay_population_explicit_champion_selection(tmp_path: Path) -> None:
    champion = (tmp_path / "champion.pth").resolve()
    other = (tmp_path / "other.pth").resolve()
    accepted = [
        {"id": "a", "source": str(other), "trusted": False},
        {"id": "b", "source": str(champion), "trusted": True},
    ]
    assert choose_champion(accepted, champion)["id"] == "b"
    assert choose_champion(accepted)["id"] == "b"


def test_generated_selfplay_honors_manifest_matchup_order() -> None:
    population = {
        "champion_id": "a",
        "matchup_order": [
            {"challenger": "b", "champion": "a"},
            {"challenger": "a", "champion": "b"},
        ],
    }
    members = {"a": {"id": "a", "file": "a.pth"}, "b": {"id": "b", "file": "b.pth"}}
    assert matchup_order(population, members) == [("b", "a"), ("a", "b")]


def test_selfplay_generation_state_resumes_without_seed_or_batch_reuse(tmp_path: Path) -> None:
    initial = load_generation_state(tmp_path, "4p", 1_000_000)
    assert initial["next_seed"] == 1_000_000
    assert initial["next_batch"] == 0
    initial["next_seed"] = 1_000_032
    initial["next_batch"] = 1
    initial["games_committed"] = 128
    state_path = save_generation_state(tmp_path, initial)
    assert state_path.is_file()

    resumed = load_generation_state(tmp_path, "4p", 1_000_000)
    assert resumed["protocol"] == GENERATION_STATE_PROTOCOL
    assert resumed["next_seed"] == 1_000_032
    assert resumed["next_batch"] == 1
    assert resumed["games_committed"] == 128

    # An explicit higher lower-bound can jump forward, but never backwards.
    advanced = load_generation_state(tmp_path, "4p", 2_000_000)
    assert advanced["next_seed"] == 2_000_000
    assert advanced["next_batch"] == 1
