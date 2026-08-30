from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from .settings import MortalRuntime, Settings, normalize_mode


class MortalController:
    def __init__(self, settings: Settings) -> None:
        self.s = settings

    def runtime(self, mode: str | None) -> MortalRuntime:
        return self.s.runtime(normalize_mode(mode))

    def status(self, mode: str = "3p") -> dict[str, Any]:
        runtime = self.runtime(mode)
        checks = {
            "root": runtime.root.exists(),
            "python": runtime.python_executable.exists(),
            "mortal_dir": runtime.mortal_dir.exists(),
            "config": runtime.config_file.exists(),
            "train": (runtime.mortal_dir / "train.py").exists(),
            "train_grp": (runtime.mortal_dir / "train_grp.py").exists(),
            "evaluate": (runtime.mortal_dir / runtime.evaluate_script).exists(),
            "server": (runtime.mortal_dir / "server.py").exists(),
            "client": (runtime.mortal_dir / "client.py").exists(),
            "libriichi_source": self._libriichi_source_exists(runtime),
        }
        return {
            "mode": runtime.mode,
            "players": runtime.players,
            "unified": runtime.unified,
            "mortal_root": str(runtime.root),
            "mode_root": str(runtime.mode_root),
            "mortal_dir": str(runtime.mortal_dir),
            "python": str(runtime.python_executable),
            "config_file": str(runtime.config_file),
            "ready": all(checks.values()),
            "checks": checks,
        }

    def all_statuses(self) -> dict[str, Any]:
        return {mode: self.status(mode) for mode in ("3p", "4p")}

    def _mortal_env(self, runtime: MortalRuntime) -> dict[str, str]:
        existing = os.environ.get("PYTHONPATH", "")
        project = str(self.s.project_root)
        mortal_dir = str(runtime.mortal_dir)
        components = [project, mortal_dir]
        if existing:
            components.append(existing)
        env = {
            "MORTAL_CFG": str(runtime.config_file),
            "MORTAL_GAME_MODE": runtime.mode,
            "MORTAL_PLAYER_COUNT": str(runtime.players),
            "PYTHONPATH": os.pathsep.join(components),
        }
        if runtime.unified:
            env["MORTAL_UNIFIED_ROOT"] = str(runtime.root)
        return env

    def command_for(self, kind: str, args: dict[str, Any] | None = None) -> tuple[list[str], Path, dict[str, str]]:
        args = args or {}
        mode = normalize_mode(str(args.get("mode", "3p")))
        runtime = self.runtime(mode)
        env = self._mortal_env(runtime)
        py = str(runtime.python_executable)
        md = runtime.mortal_dir

        table: dict[str, list[str]] = {
            "train_grp": [py, "train_grp.py"],
            "train": [py, "train.py"],
            "evaluate": [py, runtime.evaluate_script],
            "selfplay_server": [py, "server.py"],
            "selfplay_client": [py, "client.py"],
            "tensorboard": [
                py,
                "-m",
                "tensorboard.main",
                "--logdir",
                str(runtime.runs_dir),
                "--host",
                "127.0.0.1",
                "--port",
                "6006" if mode == "3p" else "6007",
            ],
        }
        if kind in table:
            self._require_runtime_ready_for_command(runtime, kind)
            return table[kind], md, env

        if kind == "patch":
            if runtime.unified:
                script = self.s.project_root / "scripts" / "patch_mortal_unified_all.py"
            elif mode == "3p":
                script = self.s.project_root / "scripts" / "patch_mortal_all.py"
            else:
                script = self.s.project_root / "scripts" / "patch_mortal_4p.py"
            return [sys.executable, str(script), "--root", str(runtime.root)], self.s.project_root, env

        if kind == "bootstrap_runtime":
            if os.name != "nt":
                raise ValueError("Mortal bootstrap currently targets Windows")
            if runtime.unified:
                script = self.s.project_root / "scripts" / "bootstrap_unified_runtime.ps1"
                cmd = [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-InstallRoot",
                    str(runtime.root),
                ]
            else:
                script = self.s.project_root / "scripts" / "bootstrap_runtime.ps1"
                cmd = [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-Mode",
                    mode,
                    "-InstallRoot",
                    str(runtime.root),
                ]
            if bool(args.get("skip_rust_build", False)):
                cmd.append("-SkipRustBuild")
            if bool(args.get("install_rust_if_missing", False)):
                cmd.append("-InstallRustIfMissing")
            return cmd, self.s.project_root, {}

        if kind == "bootstrap_unified_runtime":
            if os.name != "nt":
                raise ValueError("Unified Mortal bootstrap currently targets Windows")
            root = self.s.mortal_unified_root or (self.s.project_root.parent / "Mortal_Unified").resolve()
            script = self.s.project_root / "scripts" / "bootstrap_unified_runtime.ps1"
            cmd = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-InstallRoot",
                str(root),
            ]
            if bool(args.get("skip_rust_build", False)):
                cmd.append("-SkipRustBuild")
            if bool(args.get("install_rust_if_missing", False)):
                cmd.append("-InstallRustIfMissing")
            return cmd, self.s.project_root, {}

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
                if through not in (1, 2, 3, 4):
                    raise ValueError("MJX-Sanma patch stage must be 1, 2, 3 or 4")
                return [sys.executable, str(script), "--root", str(root), "--through", str(through)], self.s.project_root, env
            script = self.s.project_root / "scripts" / "audit_mjx_sanma.py"
            return [
                sys.executable,
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
            source = (runtime.models_dir / source_value).resolve()
            destination = (runtime.models_dir / destination_value).resolve()
            self._ensure_under(source, runtime.models_dir)
            self._ensure_under(destination, runtime.models_dir)
            if not source.is_file() or source.suffix != ".pth":
                raise ValueError(f"Candidate checkpoint must be an existing .pth file: {source}")
            if destination.suffix != ".pth":
                raise ValueError("Promotion destination must end with .pth")

            paired = self._resolve_user_path(args.get("paired_results"), must_exist=True)
            if paired.suffix.casefold() not in {".jsonl", ".json"}:
                raise ValueError("Paired evaluation results must be JSON/JSONL")
            akagi_root = self._resolve_user_path(args.get("akagi_root"), must_exist=True)
            profile = str(args.get("profile", "")).strip()
            if not profile:
                raise ValueError("A rating profile is required")

            report_dir = runtime.runs_dir / "promotion"
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

        if kind in {"convert", "tenhou_dl"} and mode != "3p":
            raise ValueError(
                "The bundled Lawrence Tenhou conversion tools are 3P-only. "
                "For 4P, point the Mortal dataset.globs setting at native 4P JSON.gz logs."
            )
        if kind in {"convert", "tenhou_dl"} and runtime.unified:
            raise ValueError(
                "The unified canonical Mortal runtime does not bundle Lawrence's legacy Tenhou tools. "
                "Keep the legacy 3P runtime for conversion, or feed converted JSON.gz logs into runtime/3p/data."
            )

        if kind == "convert":
            source = self._resolve_user_path(args.get("source"), must_exist=True)
            output = self._resolve_user_path(args.get("output"), must_exist=False)
            output.mkdir(parents=True, exist_ok=True)
            reviewer = runtime.root / "mjai-reviewer"
            return ["cargo", "run", "--example", "convert_dir", "--release", "--", str(source), str(output)], reviewer, env

        if kind == "tenhou_dl":
            source = self._resolve_user_path(args.get("source"), must_exist=True)
            output = self._resolve_user_path(args.get("output"), must_exist=False)
            output.mkdir(parents=True, exist_ok=True)
            exe = runtime.root / "tenhou_dl" / "target" / "release" / ("tenhou_dl.exe" if os.name == "nt" else "tenhou_dl")
            return [str(exe), "--format", "gz", "--mode", "3", "--input", str(source), "--output", str(output)], exe.parent, env

        raise ValueError(f"Unsupported job kind: {kind}")

    def scan_data(self, mode: str = "3p") -> dict[str, Any]:
        runtime = self.runtime(mode)
        roots = {
            "data": runtime.data_dir,
            "models": runtime.models_dir,
            "runs": runtime.runs_dir,
        }
        result: dict[str, Any] = {"mode": runtime.mode}
        for name, root in roots.items():
            files = list(root.rglob("*")) if root.exists() else []
            regular = [p for p in files if p.is_file()]
            result[name] = {
                "path": str(root),
                "files": len(regular),
                "bytes": sum(p.stat().st_size for p in regular),
            }
        if runtime.data_dir.exists():
            result["data"]["jsonl"] = len(list(runtime.data_dir.rglob("*.jsonl")))
            result["data"]["gz"] = len(list(runtime.data_dir.rglob("*.gz")))
            result["data"]["json_gz"] = len(list(runtime.data_dir.rglob("*.json.gz")))
        return result

    def checkpoints(self, mode: str = "3p") -> list[dict[str, Any]]:
        runtime = self.runtime(mode)
        if not runtime.models_dir.exists():
            return []
        rows = []
        for p in runtime.models_dir.rglob("*.pth"):
            st = p.stat()
            rows.append({
                "mode": runtime.mode,
                "name": p.name,
                "relative": str(p.relative_to(runtime.models_dir)),
                "bytes": st.st_size,
                "mtime": st.st_mtime,
            })
        return sorted(rows, key=lambda x: x["mtime"], reverse=True)

    def _require_runtime_ready_for_command(self, runtime: MortalRuntime, kind: str) -> None:
        if not runtime.python_executable.exists():
            raise ValueError(f"{runtime.mode} Python runtime is not installed: {runtime.python_executable}")
        if not runtime.config_file.exists():
            raise ValueError(f"{runtime.mode} Mortal config is missing: {runtime.config_file}")
        script = {
            "evaluate": runtime.evaluate_script,
            "train": "train.py",
            "train_grp": "train_grp.py",
            "selfplay_server": "server.py",
            "selfplay_client": "client.py",
        }.get(kind)
        if script and not (runtime.mortal_dir / script).is_file():
            raise ValueError(f"{runtime.mode} Mortal script is missing: {runtime.mortal_dir / script}")

    @staticmethod
    def _libriichi_source_exists(runtime: MortalRuntime) -> bool:
        candidates = (
            runtime.root / "libriichi" / "Cargo.toml",
            runtime.root / "Mortal" / "libriichi" / "Cargo.toml",
        )
        return any(p.is_file() for p in candidates)

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
