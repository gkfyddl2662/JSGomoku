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

    def _mortal_env(self) -> dict[str, str]:
        existing = os.environ.get("PYTHONPATH", "")
        project = str(self.s.project_root)
        pythonpath = project if not existing else project + os.pathsep + existing
        return {
            "MORTAL_CFG": str(self.s.config_file),
            "PYTHONPATH": pythonpath,
        }

    def command_for(self, kind: str, args: dict[str, Any] | None = None) -> tuple[list[str], Path, dict[str, str]]:
        args = args or {}
        env = self._mortal_env()
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
            script = self.s.project_root / "scripts" / "patch_mortal_all.py"
            return [py, str(script), "--root", str(self.s.mortal_root)], self.s.project_root, env

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
            if os.name != "nt":
                raise ValueError("MJX probe currently targets the Windows + WSL2 deployment")
            distro = str(args.get("distro", "")).strip()
            linux_root = str(args.get("linux_root", "~/mortal-rogs-mjx")).strip() or "~/mortal-rogs-mjx"
            cmd = ["wsl.exe"]
            if distro:
                cmd.extend(["-d", distro])
            probe_code = (
                "import mjx; e=mjx.MjxEnv(); o=e.reset(seed=1); "
                "assert len(o)==4; print('MJX_OK', getattr(mjx,'__version__','unknown'), sorted(o))"
            )
            bash = (
                'ROOT="${ROGS_MJX_ROOT/#\\~/$HOME}"; '
                '"$ROOT/.venv/bin/python" -c "$ROGS_MJX_PROBE"'
            )
            cmd.extend([
                "env",
                f"ROGS_MJX_ROOT={linux_root}",
                f"ROGS_MJX_PROBE={probe_code}",
                "bash",
                "-lc",
                bash,
            ])
            return cmd, self.s.project_root, {}

        if kind == "mjx_sanma_prepare":
            if os.name != "nt":
                raise ValueError("The current MJX-Sanma preparation entry point targets Windows")
            destination = str(args.get("root", "C:\\Mortal_ROGS\\mjx-sanma")).strip()
            script = self.s.project_root / "scripts" / "prepare_mjx_sanma.ps1"
            return [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-Destination",
                destination,
            ], self.s.project_root, {}

        if kind in {"mjx_sanma_patch", "mjx_sanma_audit"}:
            root = self._resolve_user_path(args.get("root"), must_exist=True)
            if kind == "mjx_sanma_patch":
                script = self.s.project_root / "scripts" / "patch_mjx_sanma.py"
                through = int(args.get("through", 3))
                if through not in (1, 2, 3):
                    raise ValueError("MJX-Sanma patch stage must be 1, 2 or 3")
                return [py, str(script), "--root", str(root), "--through", str(through)], self.s.project_root, env
            script = self.s.project_root / "scripts" / "audit_mjx_sanma.py"
            return [
                py,
                str(script),
                "--root",
                str(root),
                "--allow-changed",
                "--allow-blockers",
            ], self.s.project_root, env

        if kind == "promote_gated":
            source_value = args.get("source")
            destination_value = args.get("destination")
            if not isinstance(source_value, str) or not source_value.strip():
                raise ValueError("A candidate checkpoint relative path is required")
            if not isinstance(destination_value, str) or not destination_value.strip():
                raise ValueError("A destination checkpoint relative path is required")
            source = (self.s.models_dir / source_value).resolve()
            destination = (self.s.models_dir / destination_value).resolve()
            self._ensure_under(source, self.s.models_dir)
            self._ensure_under(destination, self.s.models_dir)
            if not source.is_file() or source.suffix != ".pth":
                raise ValueError(f"Candidate checkpoint must be an existing .pth file: {source}")
            if destination.suffix != ".pth":
                raise ValueError("Promotion destination must end with .pth")

            paired = self._resolve_user_path(args.get("paired_results"), must_exist=True)
            if paired.suffix.casefold() not in {".jsonl", ".json"}:
                raise ValueError("Paired evaluation results must be JSON/JSONL")
            akagi_root = self._resolve_user_path(args.get("akagi_root"), must_exist=True)
            mode = str(args.get("mode", "3p")).casefold()
            if mode not in {"3p", "4p"}:
                raise ValueError("Promotion mode must be 3p or 4p")
            profile = str(args.get("profile", "")).strip()
            if not profile:
                raise ValueError("A rating profile is required")

            report_dir = self.s.runs_dir / "promotion"
            report_dir.mkdir(parents=True, exist_ok=True)
            report = report_dir / f"{source.stem}-{mode}-{profile}.json"
            script = self.s.project_root / "scripts" / "promote_if_passed.py"
            cmd = [
                py,
                str(script),
                "--candidate",
                str(source),
                "--destination",
                str(destination),
                "--paired-results",
                str(paired),
                "--profile",
                profile,
                "--mode",
                mode,
                "--akagi-root",
                str(akagi_root),
                "--report",
                str(report),
            ]
            return cmd, self.s.project_root, env

        if kind == "convert":
            source = self._resolve_user_path(args.get("source"), must_exist=True)
            output = self._resolve_user_path(args.get("output"), must_exist=False)
            output.mkdir(parents=True, exist_ok=True)
            reviewer = self.s.mortal_root / "mjai-reviewer"
            return ["cargo", "run", "--example", "convert_dir", "--release", "--", str(source), str(output)], reviewer, env

        if kind == "tenhou_dl":
            source = self._resolve_user_path(args.get("source"), must_exist=True)
            output = self._resolve_user_path(args.get("output"), must_exist=False)
            output.mkdir(parents=True, exist_ok=True)
            exe = self.s.mortal_root / "tenhou_dl" / "target" / "release" / ("tenhou_dl.exe" if os.name == "nt" else "tenhou_dl")
            return [str(exe), "--format", "gz", "--mode", "3", "--input", str(source), "--output", str(output)], exe.parent, env

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
