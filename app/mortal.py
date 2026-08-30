from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any

from .settings import Settings


class MortalController:
    def __init__(self, settings: Settings) -> None:
        self.s = settings

    def status(self) -> dict[str, Any]:
        checks = {
            "root": self.s.mortal_root.exists(),
            "mortal_dir": self.s.mortal_dir.exists(),
            "config": self.s.config_file.exists(),
            "train": (self.s.mortal_dir / "train.py").exists(),
            "train_grp": (self.s.mortal_dir / "train_grp.py").exists(),
            "one_vs_two": (self.s.mortal_dir / "one_vs_two.py").exists(),
            "server": (self.s.mortal_dir / "server.py").exists(),
            "client": (self.s.mortal_dir / "client.py").exists(),
            "libriichi": self._libriichi_available(),
        }
        return {
            "mortal_root": str(self.s.mortal_root),
            "ready": all(checks.values()),
            "checks": checks,
        }

    def command_for(self, kind: str, args: dict[str, Any] | None = None) -> tuple[list[str], Path, dict[str, str]]:
        args = args or {}
        cfg = str(self.s.config_file)
        env = {"MORTAL_CFG": cfg}
        py = sys.executable
        md = self.s.mortal_dir

        table: dict[str, list[str]] = {
            "train_grp": [py, "train_grp.py"],
            "train": [py, "train.py"],
            "evaluate": [py, "one_vs_two.py"],
            "selfplay_server": [py, "server.py"],
            "selfplay_client": [py, "client.py"],
            "tensorboard": [py, "-m", "tensorboard.main", "--logdir", str(self.s.runs_dir), "--host", "127.0.0.1", "--port", "6006"],
        }
        if kind in table:
            return table[kind], md, env

        if kind == "patch":
            script = self.s.project_root / "scripts" / "patch_mortal.py"
            return [py, str(script), "--root", str(self.s.mortal_root)], self.s.project_root, {}

        if kind == "mjx_setup":
            if os.name != "nt":
                raise ValueError("MJX WSL bootstrap is only used from a Windows host")
            script = self.s.project_root / "scripts" / "setup_mjx_eval_wsl.ps1"
            if not script.exists():
                raise ValueError(f"MJX setup script not found: {script}")
            distro = str(args.get("distro", "")).strip()
            linux_root = str(args.get("linux_root", "~/mortal-rogs-mjx")).strip() or "~/mortal-rogs-mjx"
            cmd = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-LinuxRoot",
                linux_root,
            ]
            if distro:
                cmd.extend(["-Distro", distro])
            return cmd, self.s.project_root, {}

        if kind == "mjx_probe":
            script = self.s.project_root / "scripts" / "check_mjx_runtime.py"
            return [py, str(script)], self.s.project_root, {}

        if kind == "convert":
            source = self._resolve_user_path(args.get("source"), must_exist=True)
            output = self._resolve_user_path(args.get("output"), must_exist=False)
            output.mkdir(parents=True, exist_ok=True)
            reviewer = self.s.mortal_root / "mjai-reviewer"
            return ["cargo", "run", "--example", "convert_dir", "--release", "--", str(source), str(output)], reviewer, {}

        if kind == "tenhou_dl":
            source = self._resolve_user_path(args.get("source"), must_exist=True)
            output = self._resolve_user_path(args.get("output"), must_exist=False)
            output.mkdir(parents=True, exist_ok=True)
            exe = self.s.mortal_root / "tenhou_dl" / "target" / "release" / ("tenhou_dl.exe" if os.name == "nt" else "tenhou_dl")
            return [str(exe), "--format", "gz", "--mode", "3", "--input", str(source), "--output", str(output)], exe.parent, {}

        raise ValueError(f"Unsupported job kind: {kind}")

    def scan_data(self) -> dict[str, Any]:
        roots = {
            "data": self.s.data_dir,
            "models": self.s.models_dir,
            "runs": self.s.runs_dir,
        }
        result: dict[str, Any] = {}
        for name, root in roots.items():
            files = list(root.rglob("*")) if root.exists() else []
            regular = [p for p in files if p.is_file()]
            result[name] = {
                "path": str(root),
                "files": len(regular),
                "bytes": sum(p.stat().st_size for p in regular),
            }
        if self.s.data_dir.exists():
            result["data"]["jsonl"] = len(list(self.s.data_dir.rglob("*.jsonl")))
            result["data"]["gz"] = len(list(self.s.data_dir.rglob("*.gz")))
        return result

    def checkpoints(self) -> list[dict[str, Any]]:
        if not self.s.models_dir.exists():
            return []
        rows = []
        for p in self.s.models_dir.rglob("*.pth"):
            st = p.stat()
            rows.append({
                "name": p.name,
                "relative": str(p.relative_to(self.s.models_dir)),
                "bytes": st.st_size,
                "mtime": st.st_mtime,
            })
        return sorted(rows, key=lambda x: x["mtime"], reverse=True)

    def promote_checkpoint(self, source: str, destination: str = "best_sanma.pth") -> dict[str, str]:
        src = (self.s.models_dir / source).resolve()
        dst = (self.s.models_dir / destination).resolve()
        self._ensure_under(src, self.s.models_dir)
        self._ensure_under(dst, self.s.models_dir)
        if not src.exists() or src.suffix != ".pth" or dst.suffix != ".pth":
            raise ValueError("Checkpoint must be an existing .pth file")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return {"source": str(src), "destination": str(dst)}

    def _resolve_user_path(self, value: Any, must_exist: bool) -> Path:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("A path is required")
        p = Path(value).expanduser().resolve()
        if must_exist and not p.exists():
            raise ValueError(f"Path does not exist: {p}")
        return p

    @staticmethod
    def _ensure_under(path: Path, root: Path) -> None:
        try:
            path.relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError("Path escapes the allowed directory") from exc

    @staticmethod
    def _libriichi_available() -> bool:
        try:
            import libriichi  # noqa: F401
            return True
        except Exception:
            return False
