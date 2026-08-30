from __future__ import annotations

import json
import platform
import subprocess
import sys
from typing import Any


def _run(cmd: list[str], timeout: int = 5) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return (p.stdout or p.stderr).strip()
    except Exception as exc:
        return f"unavailable: {exc}"


def system_status() -> dict[str, Any]:
    query = (
        "name,driver_version,memory.total,memory.used,memory.free,"
        "utilization.gpu,temperature.gpu,power.draw,power.limit"
    )
    raw = _run([
        "nvidia-smi",
        f"--query-gpu={query}",
        "--format=csv,noheader,nounits",
    ])
    gpus = []
    if raw and not raw.startswith("unavailable"):
        for idx, line in enumerate(raw.splitlines()):
            parts = [x.strip() for x in line.split(",")]
            if len(parts) >= 9:
                gpus.append({
                    "index": idx,
                    "name": parts[0],
                    "driver": parts[1],
                    "memory_total_mb": _num(parts[2]),
                    "memory_used_mb": _num(parts[3]),
                    "memory_free_mb": _num(parts[4]),
                    "utilization_pct": _num(parts[5]),
                    "temperature_c": _num(parts[6]),
                    "power_w": _num(parts[7]),
                    "power_limit_w": _num(parts[8]),
                })

    torch_info: dict[str, Any]
    probe = (
        "import json,torch; "
        "print(json.dumps({'version':torch.__version__,'cuda':torch.version.cuda,"
        "'available':torch.cuda.is_available(),'device':torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,"
        "'capability':torch.cuda.get_device_capability(0) if torch.cuda.is_available() else None}))"
    )
    torch_raw = _run([sys.executable, "-c", probe])
    try:
        torch_info = json.loads(torch_raw)
    except Exception:
        torch_info = {"available": False, "detail": torch_raw}

    return {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "gpus": gpus,
        "nvidia_smi": raw if not gpus else None,
        "torch": torch_info,
    }


def _num(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None
