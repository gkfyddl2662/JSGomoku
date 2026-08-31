from __future__ import annotations

from pathlib import Path


def test_akagi_3p_compat_contract_is_pinned() -> None:
    root = Path(__file__).resolve().parents[1]
    helper = (root / "scripts" / "akagi_3p_compat.py").read_text(encoding="utf-8")
    evaluator = (root / "scripts" / "patch_mortal_unified_eval_stage5c.py").read_text(encoding="utf-8")
    arena_patch = (root / "scripts" / "patch_mortal_akagi_legacy_arena.py").read_text(encoding="utf-8")
    installer = (root / "scripts" / "install_population_champion.py").read_text(encoding="utf-8")

    assert 'AKAGI_PIN = "11c0ffc0d70bf8142585b92405b4412976c9e205"' in helper
    assert "LEGACY_3P_OBS_CHANNELS = 775" in helper
    assert "LEGACY_3P_ACTION_SPACE = 44" in helper
    assert "hasattr(libriichi3p.arena, 'OneVsTwo')" in helper
    assert '"patch_mortal_akagi_legacy_arena.py"' in helper
    assert "engine_type = 'mjai-log'" in evaluator
    assert "AKAGI_LEGACY_OBS_CHANNELS = 775" in evaluator
    assert "NATIVE_OBS_CHANNELS = 1010" in evaluator
    assert "MORTAL_ROGS_AKAGI_LEGACY_ARENA_V2" in arena_patch
    assert "source=akagi-libriichi3p" in arena_patch
    assert "source=unified-libriichi" in arena_patch
    assert "getattr(lib, 'arena', None)" in arena_patch
    assert "from libriichi.arena import OneVsTwo as arena_cls" in arena_patch
    assert 'LEGACY_3P_SLOT = "akagi_legacy_champion.pth"' in installer
    assert 'LEGACY_3P_ABI_KIND = "akagi-legacy-775"' in installer


def test_population_launcher_uses_compat_validator() -> None:
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "RUN_SELFPLAY_POPULATION.bat").read_text(encoding="utf-8")
    wrapper = (root / "scripts" / "prepare_selfplay_population_compat.py").read_text(encoding="utf-8")

    assert "prepare_selfplay_population_compat.py" in launcher
    assert "checkpoint_obs_channels(checkpoint)" in wrapper
    assert '"abi_kind": "akagi-legacy-775"' in wrapper
    assert "ensure_akagi_3p_compat(runtime_root)" in wrapper
    assert "apply_runtime_evaluator(runtime_root, base.PROJECT_ROOT)" in wrapper
