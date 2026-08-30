from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


RUST_STAGES = (
    "patch_libriichi_unified_stage1.py",
    "patch_libriichi_unified_stage2.py",
    "patch_libriichi_unified_stage3a.py",
    "patch_libriichi_unified_stage3b.py",
    "patch_libriichi_unified_stage3c.py",
    "patch_libriichi_unified_stage3d.py",
    "patch_libriichi_unified_stage3e_fixed.py",
    "patch_libriichi_unified_stage3f.py",
    "patch_libriichi_unified_arena_stage4a.py",
    "patch_libriichi_unified_arena_stage4b.py",
    "patch_libriichi_unified_arena_stage4c.py",
    "patch_libriichi_unified_game_stage5a.py",
    "patch_libriichi_unified_game_stage5a_fix.py",
    "patch_libriichi_unified_game_stage5b.py",
    "patch_libriichi_unified_grp_stage6a.py",
)

PYTHON_STAGES = (
    "patch_mortal_unified_stage1.py",
    "patch_mortal_unified_stage2.py",
    "patch_mortal_unified_eval_stage5c.py",
    "patch_mortal_unified_grp_stage6b.py",
    "patch_mortal_4p.py",
)


def run_stage(script_dir: Path, script_name: str, root: Path) -> None:
    script = script_dir / script_name
    if not script.is_file():
        raise RuntimeError(f"missing patch stage: {script}")
    print(f"[unified] {script_name}")
    subprocess.run(
        [sys.executable, str(script), "--root", str(root)],
        check=True,
    )


def apply(root: Path, *, rust_only: bool = False, python_only: bool = False) -> None:
    if rust_only and python_only:
        raise ValueError("--rust-only and --python-only are mutually exclusive")
    root = root.expanduser().resolve()
    if not (root / "libriichi").is_dir() or not (root / "mortal").is_dir():
        raise RuntimeError(f"expected canonical Equim Mortal clone: {root}")

    script_dir = Path(__file__).resolve().parent
    if not python_only:
        for stage in RUST_STAGES:
            run_stage(script_dir, stage, root)
    if not rust_only:
        for stage in PYTHON_STAGES:
            run_stage(script_dir, stage, root)

    if not python_only:
        consts = (root / "libriichi/src/consts.rs").read_text(encoding="utf-8")
        if (
            "ACTION_SPACE_3P: usize = 44" not in consts
            or "ACTION_SPACE_4P: usize = 46" not in consts
        ):
            raise RuntimeError("unified action ABI postcondition failed")
        if "MORTAL_ROGS_UNIFIED_ACTION_OBS_STAGE3E" not in consts:
            raise RuntimeError("unified observation ABI stage postcondition failed")
        if "MORTAL_ROGS_UNIFIED_ARENA_STAGE4C" not in consts or "4 => Ok((170, 34))" not in consts:
            raise RuntimeError("unified 3P oracle ABI stage postcondition failed")

    if not rust_only:
        model = (root / "mortal/model.py").read_text(encoding="utf-8")
        train = (root / "mortal/train.py").read_text(encoding="utf-8")
        train_grp = (root / "mortal/train_grp.py").read_text(encoding="utf-8")
        evaluator = (root / "mortal/one_vs_two.py").read_text(encoding="utf-8")
        if "MORTAL_ROGS_UNIFIED_MODEL_STAGE1" not in model:
            raise RuntimeError("unified Python model postcondition failed")
        if "MORTAL_ROGS_UNIFIED_TRAINER_STAGE2" not in train:
            raise RuntimeError("unified trainer postcondition failed")
        if "MORTAL_ROGS_UNIFIED_GRP_TRAINER_STAGE6B" not in train_grp:
            raise RuntimeError("unified GRP trainer postcondition failed")
        if "MORTAL_ROGS_UNIFIED_EVAL_STAGE5C" not in evaluator:
            raise RuntimeError("unified 3P evaluator postcondition failed")

    mode = "rust" if rust_only else "python" if python_only else "all"
    print(f"MORTAL_UNIFIED_PATCH_ALL_OK mode={mode} root={root}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Apply the complete single-runtime Mortal 3P/4P patch chain.")
    ap.add_argument("--root", type=Path, required=True)
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--rust-only", action="store_true")
    group.add_argument("--python-only", action="store_true")
    args = ap.parse_args()
    apply(args.root, rust_only=args.rust_only, python_only=args.python_only)


if __name__ == "__main__":
    main()
