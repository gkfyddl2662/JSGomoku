from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"Patch anchor not found: {label}")
    return text.replace(old, new, 1)


def patch_file(path: Path, transform) -> None:
    original = path.read_text(encoding="utf-8")
    updated = transform(original)
    if updated == original:
        print(f"unchanged: {path}")
        return
    backup = path.with_suffix(path.suffix + ".webui.bak")
    if not backup.exists():
        shutil.copy2(path, backup)
    path.write_text(updated, encoding="utf-8")
    print(f"patched: {path}")


def patch_train(text: str) -> str:
    text = replace_once(
        text,
        "    enable_amp = config['control']['enable_amp']\n    enable_compile = config['control']['enable_compile']\n",
        "    enable_amp = config['control']['enable_amp']\n    enable_compile = config['control']['enable_compile']\n"
        "    perf = config.get('performance', {})\n"
        "    amp_dtype_name = perf.get('amp_dtype', 'float16')\n"
        "    amp_dtype = torch.bfloat16 if amp_dtype_name == 'bfloat16' else torch.float16\n"
        "    non_blocking = bool(perf.get('non_blocking_transfer', device.type == 'cuda'))\n"
        "    if device.type == 'cuda':\n"
        "        torch.backends.cuda.matmul.allow_tf32 = bool(perf.get('allow_tf32', True))\n"
        "        torch.backends.cudnn.allow_tf32 = bool(perf.get('allow_tf32', True))\n"
        "        torch.set_float32_matmul_precision(perf.get('matmul_precision', 'high'))\n",
        "train performance setup",
    )
    text = replace_once(
        text,
        "            pin_memory = True,\n            worker_init_fn = worker_init_fn,\n",
        "            pin_memory = config['dataset'].get('pin_memory', True),\n"
        "            persistent_workers = config['dataset'].get('persistent_workers', num_workers > 0) if num_workers > 0 else False,\n"
        "            prefetch_factor = config['dataset'].get('prefetch_factor', 2) if num_workers > 0 else None,\n"
        "            worker_init_fn = worker_init_fn,\n",
        "dataloader tuning",
    )
    text = text.replace(".to(dtype=torch.float32, device=device)", ".to(dtype=torch.float32, device=device, non_blocking=non_blocking)")
    text = text.replace(".to(dtype=torch.int64, device=device)", ".to(dtype=torch.int64, device=device, non_blocking=non_blocking)")
    text = text.replace(".to(dtype=torch.bool, device=device)", ".to(dtype=torch.bool, device=device, non_blocking=non_blocking)")
    text = text.replace(".to(dtype=torch.float64, device=device)", ".to(dtype=torch.float64, device=device, non_blocking=non_blocking)")
    text = replace_once(
        text,
        "            with torch.autocast(device.type, enabled=enable_amp):\n",
        "            with torch.autocast(device.type, dtype=amp_dtype if device.type == 'cuda' else None, enabled=enable_amp):\n",
        "autocast dtype",
    )
    return text


def patch_model(text: str) -> str:
    text = replace_once(
        text,
        "    def __init__(self, hidden_size=64, num_layers=2, num_players=4):\n",
        "    def __init__(self, hidden_size=64, num_layers=2, num_players=4, dtype=torch.float64):\n",
        "GRP dtype argument",
    )
    text = replace_once(
        text,
        "            mod.to(torch.float64)\n",
        "            mod.to(dtype=dtype)\n",
        "GRP module dtype",
    )
    return text


def patch_grp(text: str) -> str:
    text = replace_once(
        text,
        "    device = torch.device(cfg['control']['device'])\n    torch.backends.cudnn.benchmark = cfg['control']['enable_cudnn_benchmark']\n",
        "    device = torch.device(cfg['control']['device'])\n"
        "    torch.backends.cudnn.benchmark = cfg['control']['enable_cudnn_benchmark']\n"
        "    dtype_name = cfg['control'].get('dtype', 'float64')\n"
        "    dtype = torch.float32 if dtype_name == 'float32' else torch.float64\n"
        "    num_workers = int(cfg['control'].get('num_workers', 1))\n"
        "    if device.type == 'cuda':\n"
        "        torch.backends.cuda.matmul.allow_tf32 = True\n"
        "        torch.backends.cudnn.allow_tf32 = True\n"
        "        torch.set_float32_matmul_precision('high')\n",
        "GRP performance setup",
    )
    text = replace_once(
        text,
        "    grp = GRP(**cfg['network'], num_players=num_players).to(device)\n",
        "    grp = GRP(**cfg['network'], num_players=num_players, dtype=dtype).to(device)\n",
        "GRP dtype construction",
    )
    text = text.replace("dtype=np.float64", "dtype=np.float32 if config['grp']['control'].get('dtype', 'float64') == 'float32' else np.float64")
    text = text.replace("num_workers = 1,\n        collate_fn = collate,", "num_workers = num_workers,\n        pin_memory = cfg['control'].get('pin_memory', True),\n        persistent_workers = cfg['control'].get('persistent_workers', num_workers > 0) if num_workers > 0 else False,\n        prefetch_factor = cfg['control'].get('prefetch_factor', 2) if num_workers > 0 else None,\n        collate_fn = collate,")
    text = text.replace("inputs = inputs.to(dtype=torch.float64, device=device)", "inputs = inputs.to(dtype=dtype, device=device, non_blocking=True)")
    text = text.replace("rank_by_players = rank_by_players.to(dtype=torch.int64, device=device)", "rank_by_players = rank_by_players.to(dtype=torch.int64, device=device, non_blocking=True)")
    text = text.replace(".to(torch.float64).mean()", ".to(dtype).mean()")
    return text


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="Path to Lawrencelea/Mortal_Sanma clone")
    args = ap.parse_args()
    root = Path(args.root).expanduser().resolve()
    mortal = root / "Mortal" / "mortal"
    for required in (mortal / "train.py", mortal / "train_grp.py", mortal / "model.py"):
        if not required.exists():
            raise SystemExit(f"Missing expected upstream file: {required}")

    patch_file(mortal / "train.py", patch_train)
    patch_file(mortal / "model.py", patch_model)
    patch_file(mortal / "train_grp.py", patch_grp)
    print("Mortal RTX 5080 patch applied successfully.")


if __name__ == "__main__":
    main()
