from __future__ import annotations

from pathlib import Path
import re


DOTTED_ARENA_IMPORT_RE = re.compile(r"^\s*from libriichi\.arena import\b", re.MULTILINE)


def _has_dotted_arena_import(text: str) -> bool:
    return DOTTED_ARENA_IMPORT_RE.search(text) is not None


def test_akagi_3p_compat_contract_is_pinned() -> None:
    root = Path(__file__).resolve().parents[1]
    helper = (root / "scripts" / "akagi_3p_compat.py").read_text(encoding="utf-8")
    evaluator = (root / "scripts" / "patch_mortal_unified_eval_stage5c.py").read_text(encoding="utf-8")
    evaluator_4p = (root / "scripts" / "patch_mortal_unified_eval_stage8c.py").read_text(encoding="utf-8")
    rebuild = (root / "scripts" / "rebuild_unified_libriichi.ps1").read_text(encoding="utf-8")
    installer = (root / "scripts" / "install_population_champion.py").read_text(encoding="utf-8")

    assert 'AKAGI_PIN = "11c0ffc0d70bf8142585b92405b4412976c9e205"' in helper
    assert "LEGACY_3P_OBS_CHANNELS = 775" in helper
    assert "LEGACY_3P_ACTION_SPACE = 44" in helper
    assert "libriichi3p.mjai.Bot" in helper
    assert "ensure_unified_3p_arena" in helper
    assert '"rebuild_unified_libriichi.ps1"' in helper
    assert '"patch_mortal_unified_python_abi_stage8a.py"' in helper
    assert "hasattr(libriichi, 'arena')" in helper
    assert "hasattr(libriichi.arena, 'OneVsTwo')" in helper
    assert not _has_dotted_arena_import(helper)

    assert "engine_type = 'mjai-log'" in evaluator
    assert "AKAGI_LEGACY_OBS_CHANNELS = 775" in evaluator
    assert "NATIVE_OBS_CHANNELS = 1010" in evaluator
    assert "from libriichi import arena" in evaluator
    assert "arena.OneVsTwo" in evaluator
    assert not _has_dotted_arena_import(evaluator)

    assert "from libriichi import arena" in evaluator_4p
    assert "arena.OneVsThree" in evaluator_4p
    assert not _has_dotted_arena_import(evaluator_4p)

    assert "m.add_class::<OneVsTwo>()?;" in rebuild
    assert "maturin develop --release" in rebuild
    assert "MORTAL_UNIFIED_3P_ARENA_READY" in rebuild
    assert "hasattr(libriichi, 'arena')" in rebuild
    assert "hasattr(libriichi.arena, 'OneVsTwo')" in rebuild
    assert not _has_dotted_arena_import(rebuild)
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
