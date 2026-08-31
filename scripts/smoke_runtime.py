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
    parser = argparse.ArgumentParser(description="Smoke-test one isolated Mortal runtime.")
    parser.add_argument("--mode", choices=("3p", "4p"), required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--skip-compile", action="store_true")
    parser.add_argument("--skip-training-step", action="store_true")
    args = parser.parse_args()

    mode = args.mode
    root = args.runtime_root.expanduser().resolve()
    if mode == "3p":
        mortal_dir = root / "Mortal" / "mortal"
        config_file = mortal_dir / "config.sanma.toml"
        expected_actions = 44
        expected_v4_channels = 1010
    else:
        mortal_dir = root / "mortal"
        config_file = mortal_dir / "config.toml"
        expected_actions = 46
        expected_v4_channels = 1012

    if not mortal_dir.is_dir():
        fail(f"Mortal directory missing: {mortal_dir}")
    if not config_file.is_file():
        fail(f"Mortal config missing: {config_file}")

    import toml
    import torch
    import libriichi
    from libriichi import consts

    action_space = int(consts.ACTION_SPACE)
    if action_space != expected_actions:
        fail(
            f"Wrong libriichi ABI for {mode}: ACTION_SPACE={action_space}, "
            f"expected {expected_actions}. The 3P/4P Python environments are likely mixed."
        )

    v4_shape = tuple(int(x) for x in consts.obs_shape(4))
    if v4_shape != (expected_v4_channels, 34):
        fail(
            f"Wrong v4 observation ABI for {mode}: obs_shape(4)={v4_shape}, "
            f"expected ({expected_v4_channels}, 34)."
        )

    config = toml.load(config_file)
    version = int(config["control"]["version"])
    max_version = int(consts.MAX_VERSION)
    if version > max_version:
        fail(f"Config requests Mortal v{version}, but loaded libriichi supports only v{max_version}")

    if not torch.cuda.is_available():
        fail("torch.cuda.is_available() is false; the RTX/CUDA runtime is not usable")
    if not torch.cuda.is_bf16_supported():
        fail("CUDA is available but BF16 is not supported by the active GPU/runtime")

    device = torch.device("cuda:0")
    gpu_name = torch.cuda.get_device_name(device)
    capability = tuple(int(x) for x in torch.cuda.get_device_capability(device))
    torch.cuda.reset_peak_memory_stats(device)
    torch.set_float32_matmul_precision("high")
    torch.backends.cuda.matmul.allow_tf32 = True

    # Fast Blackwell/PyTorch kernel probe.
    a = torch.randn((512, 512), device=device, dtype=torch.bfloat16)
    b = torch.randn((512, 512), device=device, dtype=torch.bfloat16)
    c = a @ b
    torch.cuda.synchronize(device)
    if not bool(torch.isfinite(c).all().item()):
        fail("BF16 CUDA matmul produced non-finite values")

    compile_ok = None
    if not args.skip_compile and bool(config.get("control", {}).get("enable_compile", False)):
        def compiled_mm(x: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
            return torch.relu(x @ y)

        compiled = torch.compile(compiled_mm)
        compiled_out = compiled(a, b)
        torch.cuda.synchronize(device)
        if compiled_out.shape != c.shape or not bool(torch.isfinite(compiled_out).all().item()):
            fail("torch.compile CUDA smoke result is invalid")
        compile_ok = True

    sys.path.insert(0, str(mortal_dir))
    model = importlib.import_module("model")
    obs_channels, obs_tiles = (int(x) for x in consts.obs_shape(version))
    conv_channels = int(config.get("resnet", {}).get("conv_channels", 192))
    num_blocks = int(config.get("resnet", {}).get("num_blocks", 40))

    brain = model.Brain(
        conv_channels=conv_channels,
        num_blocks=num_blocks,
        version=version,
    ).to(device)
    dqn = model.DQN(version=version).to(device)

    # Actual configured network forward pass with the real ABI.
    brain.eval()
    dqn.eval()
    obs = torch.randn((1, obs_channels, obs_tiles), device=device, dtype=torch.float32)
    mask = torch.ones((1, action_space), device=device, dtype=torch.bool)
    amp_enabled = bool(config.get("control", {}).get("enable_amp", True))
    with torch.inference_mode(), torch.autocast(
        device_type="cuda", dtype=torch.bfloat16, enabled=amp_enabled
    ):
        phi = brain(obs)
        q = dqn(phi, mask)
    torch.cuda.synchronize(device)
    if tuple(q.shape) != (1, action_space):
        fail(f"Configured Mortal forward shape is {tuple(q.shape)}, expected (1, {action_space})")
    if not bool(torch.isfinite(q).all().item()):
        fail("Configured Mortal forward pass produced non-finite Q values")

    training_step_ok = None
    if not args.skip_training_step:
        # One synthetic optimizer step catches CUDA/autocast/backprop/optimizer failures
        # without requiring real game logs.
        brain.train()
        dqn.train()
        optimizer = torch.optim.AdamW(
            [*brain.parameters(), *dqn.parameters()], lr=1e-5, weight_decay=0.0
        )
        optimizer.zero_grad(set_to_none=True)
        train_obs = torch.randn((2, obs_channels, obs_tiles), device=device)
        train_mask = torch.ones((2, action_space), device=device, dtype=torch.bool)
        target = torch.zeros((2,), device=device)
        with torch.autocast(device_type="cuda", dtype=torch.bfloat16, enabled=amp_enabled):
            train_phi = brain(train_obs)
            train_q = dqn(train_phi, train_mask)
            pred = train_q[:, 0]
            loss = torch.nn.functional.smooth_l1_loss(pred.float(), target)
        if not math.isfinite(float(loss.detach().cpu())):
            fail("Synthetic training loss is non-finite")
        loss.backward()
        optimizer.step()
        torch.cuda.synchronize(device)
        training_step_ok = True

    result = {
        "ok": True,
        "mode": mode,
        "python": sys.executable,
        "python_prefix": sys.prefix,
        "runtime_root": str(root),
        "config": str(config_file),
        "config_version": version,
        "libriichi_file": getattr(libriichi, "__file__", None),
        "libriichi_version": getattr(libriichi, "__version__", None),
        "libriichi_max_version": max_version,
        "action_space": action_space,
        "obs_shape": list(consts.obs_shape(version)),
        "obs_shape_v4": list(v4_shape),
        "gpu": gpu_name,
        "cuda": torch.version.cuda,
        "torch": torch.__version__,
        "capability": list(capability),
        "bf16": True,
        "compile": compile_ok,
        "training_step": training_step_ok,
        "peak_vram_mb": round(torch.cuda.max_memory_allocated(device) / 1024**2, 1),
    }
    print("MORTAL_RUNTIME_SMOKE_OK")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
