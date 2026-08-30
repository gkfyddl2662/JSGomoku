from __future__ import annotations

import argparse
import importlib
import json
import math
import sys
from pathlib import Path


def fail(message: str) -> None:
    raise RuntimeError(message)


def main() -> int:
    ap = argparse.ArgumentParser(description="Smoke-test one unified Mortal 3P/4P runtime.")
    ap.add_argument("--runtime-root", type=Path, required=True)
    ap.add_argument("--skip-compile", action="store_true")
    ap.add_argument("--skip-training-step", action="store_true")
    args = ap.parse_args()

    root = args.runtime_root.expanduser().resolve()
    mortal_dir = root / "mortal"
    if not mortal_dir.is_dir():
        fail(f"Mortal directory missing: {mortal_dir}")

    import toml
    import torch
    import libriichi
    from libriichi import consts

    if int(consts.MAX_VERSION) != 4:
        fail(f"Unified libriichi MAX_VERSION={consts.MAX_VERSION}, expected 4")

    contracts = {
        "3p": {"players": 3, "actions": 44, "obs": 1010, "oracle": 170, "grp": 6},
        "4p": {"players": 4, "actions": 46, "obs": 1012, "oracle": 217, "grp": 7},
    }
    for mode, c in contracts.items():
        if int(consts.num_players_for(mode)) != c["players"]:
            fail(f"{mode} num_players contract failed")
        if int(consts.action_space_for(mode)) != c["actions"]:
            fail(f"{mode} action-space contract failed")
        if int(consts.grp_size_for(mode)) != c["grp"]:
            fail(f"{mode} GRP-size contract failed")
        if tuple(consts.obs_shape_for(mode, 4)) != (c["obs"], 34):
            fail(f"{mode} observation contract failed: {consts.obs_shape_for(mode, 4)}")
        if tuple(consts.oracle_obs_shape_for(mode, 4)) != (c["oracle"], 34):
            fail(f"{mode} oracle contract failed: {consts.oracle_obs_shape_for(mode, 4)}")

    arena = getattr(libriichi, "arena", None)
    if arena is None or not hasattr(arena, "OneVsTwo") or not hasattr(arena, "OneVsThree"):
        fail("Unified evaluator classes OneVsTwo/OneVsThree are not both exported")

    if not torch.cuda.is_available():
        fail("torch.cuda.is_available() is false")
    if not torch.cuda.is_bf16_supported():
        fail("CUDA is available but BF16 is not supported")

    device = torch.device("cuda:0")
    torch.cuda.reset_peak_memory_stats(device)
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    torch.set_float32_matmul_precision("high")

    a = torch.randn((512, 512), device=device, dtype=torch.bfloat16)
    b = torch.randn((512, 512), device=device, dtype=torch.bfloat16)
    mm = a @ b
    torch.cuda.synchronize(device)
    if not bool(torch.isfinite(mm).all().item()):
        fail("BF16 CUDA matmul produced non-finite values")

    compile_ok = None
    if not args.skip_compile:
        def compiled_mm(x: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
            return torch.relu(x @ y)
        compiled = torch.compile(compiled_mm)
        out = compiled(a, b)
        torch.cuda.synchronize(device)
        if out.shape != mm.shape or not bool(torch.isfinite(out).all().item()):
            fail("torch.compile CUDA probe failed")
        compile_ok = True
    del a, b, mm

    sys.path.insert(0, str(mortal_dir))
    model = importlib.import_module("model")
    mode_results = {}

    for mode, c in contracts.items():
        cfg_path = mortal_dir / f"config.{mode}.toml"
        if not cfg_path.is_file():
            fail(f"missing unified config: {cfg_path}")
        cfg = toml.load(cfg_path)
        if int(cfg["control"]["version"]) != 4:
            fail(f"{mode} config is not Mortal v4")
        if str(cfg["game"]["mode"]).casefold() != mode:
            fail(f"{mode} config game.mode mismatch")
        if int(cfg["game"]["action_space"]) != c["actions"]:
            fail(f"{mode} config action_space mismatch")

        conv_channels = int(cfg.get("resnet", {}).get("conv_channels", 192))
        num_blocks = int(cfg.get("resnet", {}).get("num_blocks", 40))
        brain = model.Brain(
            version=4,
            conv_channels=conv_channels,
            num_blocks=num_blocks,
            obs_channels=c["obs"],
            oracle_obs_channels=c["oracle"],
        ).to(device)
        dqn = model.DQN(version=4, action_space=c["actions"]).to(device)
        brain.eval()
        dqn.eval()

        obs = torch.randn((1, c["obs"], 34), device=device)
        mask = torch.ones((1, c["actions"]), device=device, dtype=torch.bool)
        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
            phi = brain(obs)
            q = dqn(phi, mask)
        torch.cuda.synchronize(device)
        if tuple(phi.shape) != (1, 1024) or tuple(q.shape) != (1, c["actions"]):
            fail(f"{mode} configured forward shape failed: phi={tuple(phi.shape)} q={tuple(q.shape)}")
        if not bool(torch.isfinite(q).all().item()):
            fail(f"{mode} forward produced non-finite Q values")

        train_ok = None
        if not args.skip_training_step:
            brain.train()
            dqn.train()
            optimizer = torch.optim.AdamW([*brain.parameters(), *dqn.parameters()], lr=1e-5, weight_decay=0.0)
            optimizer.zero_grad(set_to_none=True)
            train_obs = torch.randn((2, c["obs"], 34), device=device)
            train_mask = torch.ones((2, c["actions"]), device=device, dtype=torch.bool)
            target = torch.zeros((2,), device=device)
            with torch.autocast("cuda", dtype=torch.bfloat16):
                train_q = dqn(brain(train_obs), train_mask)
                loss = torch.nn.functional.smooth_l1_loss(train_q[:, 0].float(), target)
            if not math.isfinite(float(loss.detach().cpu())):
                fail(f"{mode} synthetic training loss is non-finite")
            loss.backward()
            optimizer.step()
            torch.cuda.synchronize(device)
            train_ok = True

        mode_results[mode] = {
            "players": c["players"],
            "actions": c["actions"],
            "obs_shape": [c["obs"], 34],
            "oracle_obs_shape": [c["oracle"], 34],
            "grp_size": c["grp"],
            "config": str(cfg_path),
            "training_step": train_ok,
        }
        del brain, dqn, obs, mask, phi, q
        if not args.skip_training_step:
            del optimizer, train_obs, train_mask, target, train_q, loss
        torch.cuda.empty_cache()

    result = {
        "ok": True,
        "python": sys.executable,
        "python_prefix": sys.prefix,
        "runtime_root": str(root),
        "libriichi_file": getattr(libriichi, "__file__", None),
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "gpu": torch.cuda.get_device_name(device),
        "capability": list(torch.cuda.get_device_capability(device)),
        "bf16": True,
        "compile": compile_ok,
        "modes": mode_results,
        "peak_vram_mb": round(torch.cuda.max_memory_allocated(device) / 1024**2, 1),
    }
    print("MORTAL_UNIFIED_RUNTIME_SMOKE_OK")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
