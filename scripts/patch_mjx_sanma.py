from __future__ import annotations

import argparse
import json
from pathlib import Path

from audit_mjx_sanma import audit
from patch_mjx_sanma_stage1 import apply as apply_stage1
from patch_mjx_sanma_stage2 import apply as apply_stage2
from patch_mjx_sanma_stage3 import apply as apply_stage3
from patch_mjx_sanma_stage4 import apply as apply_stage4


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--through", type=int, choices=(1, 2, 3, 4), default=4)
    args = parser.parse_args()

    root = args.root.resolve()
    manifest = Path(__file__).resolve().parents[1] / "mjx_sanma" / "manifest.toml"

    pre = audit(root, manifest)
    if pre["missing_files"]:
        raise RuntimeError("MJX source is incomplete; run prepare_mjx_sanma.ps1 first")

    if args.through >= 1:
        apply_stage1(root)
        print("stage 1/4: rule + tile set OK", flush=True)
    if args.through >= 2:
        apply_stage2(root)
        print("stage 2/4: wall + deal OK", flush=True)
    if args.through >= 3:
        apply_stage3(root)
        print("stage 3/4: nuki protocol OK", flush=True)
    if args.through >= 4:
        apply_stage4(root)
        print("stage 4/4: state + scoring + round flow OK", flush=True)

    post = audit(root, manifest)
    print(json.dumps(post, indent=2, ensure_ascii=False))
    print(
        "MJX_SANMA_PATCH_PARTIAL_OK: stages 1-4 applied; production remains disabled "
        "until legal-action/nuki transition, bindings/runner, and libriichi3p parity stages pass.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
