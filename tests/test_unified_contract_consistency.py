from __future__ import annotations

from pathlib import Path
import tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_sanma_oracle_contract_matches_manifest_bootstrap_and_native_patch() -> None:
    with (PROJECT_ROOT / "mortal_unified" / "manifest.toml").open("rb") as f:
        manifest = tomllib.load(f)

    assert manifest["modes"]["3p"]["oracle_obs_channels_v4"] == 170
    assert manifest["modes"]["4p"]["oracle_obs_channels_v4"] == 217

    bootstrap = (PROJECT_ROOT / "scripts" / "bootstrap_unified_runtime.ps1").read_text(encoding="utf-8")
    assert "('3p', 3, 44, 1010, 170, 6, 'rtx5080.sanma.toml')" in bootstrap
    assert "assert consts.oracle_obs_shape_for('3p', 4) == (170, 34)" in bootstrap
    assert "assert consts.oracle_obs_shape_for('4p', 4) == (217, 34)" in bootstrap

    stage4c = (PROJECT_ROOT / "scripts" / "patch_libriichi_unified_arena_stage4c.py").read_text(
        encoding="utf-8"
    )
    assert '4 => Ok((170, 34))' in stage4c
    assert 'assert_eq!(obs.dim(), (170, 34));' in stage4c
    assert 'assert_eq!(obs.dim(), (217, 34));' in stage4c

    patch_all = (PROJECT_ROOT / "scripts" / "patch_mortal_unified_all.py").read_text(encoding="utf-8")
    assert '"4 => Ok((170, 34))" not in consts' in patch_all
