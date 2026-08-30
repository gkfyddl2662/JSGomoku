from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MortalRuntime:
    mode: str
    players: int
    root: Path
    mortal_dir: Path
    config_file: Path
    python_executable: Path
    evaluate_script: str
    storage_root: Path | None = None
    unified: bool = False

    @property
    def mode_root(self) -> Path:
        return self.storage_root or self.root

    @property
    def models_dir(self) -> Path:
        return self.mode_root / "models"

    @property
    def data_dir(self) -> Path:
        return self.mode_root / "data"

    @property
    def runs_dir(self) -> Path:
        return self.mode_root / "runs"


@dataclass(frozen=True)
class Settings:
    project_root: Path
    mortal_3p_root: Path
    mortal_4p_root: Path
    host: str
    port: int
    runtime_root: Path | None = None
    mortal_unified_root: Path | None = None

    def runtime(self, mode: str) -> MortalRuntime:
        normalized = normalize_mode(mode)

        if self.mortal_unified_root is not None:
            root = self.mortal_unified_root
            mortal_dir = root / "mortal"
            python_executable = root / ".venv" / (
                "Scripts/python.exe" if os.name == "nt" else "bin/python"
            )
            return MortalRuntime(
                mode=normalized,
                players=3 if normalized == "3p" else 4,
                root=root,
                mortal_dir=mortal_dir,
                config_file=mortal_dir / f"config.{normalized}.toml",
                python_executable=python_executable,
                evaluate_script="one_vs_two.py" if normalized == "3p" else "one_vs_three.py",
                storage_root=root / "runtime" / normalized,
                unified=True,
            )

        root = self.mortal_3p_root if normalized == "3p" else self.mortal_4p_root
        python_executable = root / ".venv" / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )

        if normalized == "3p":
            mortal_dir = root / "Mortal" / "mortal"
            return MortalRuntime(
                mode="3p",
                players=3,
                root=root,
                mortal_dir=mortal_dir,
                config_file=mortal_dir / "config.sanma.toml",
                python_executable=python_executable,
                evaluate_script="one_vs_two.py",
            )

        mortal_dir = root / "mortal"
        return MortalRuntime(
            mode="4p",
            players=4,
            root=root,
            mortal_dir=mortal_dir,
            config_file=mortal_dir / "config.toml",
            python_executable=python_executable,
            evaluate_script="one_vs_three.py",
        )

    # Backward-compatible aliases. New code should call runtime(mode).
    @property
    def mortal_root(self) -> Path:
        return self.runtime("3p").root

    @property
    def mortal_dir(self) -> Path:
        return self.runtime("3p").mortal_dir

    @property
    def config_file(self) -> Path:
        return self.runtime("3p").config_file

    @property
    def models_dir(self) -> Path:
        return self.runtime("3p").models_dir

    @property
    def data_dir(self) -> Path:
        return self.runtime("3p").data_dir

    @property
    def runs_dir(self) -> Path:
        return self.runtime("3p").runs_dir


def normalize_mode(mode: str | None) -> str:
    normalized = (mode or "3p").strip().casefold()
    aliases = {
        "3": "3p",
        "3p": "3p",
        "sanma": "3p",
        "4": "4p",
        "4p": "4p",
        "yonma": "4p",
    }
    try:
        return aliases[normalized]
    except KeyError as exc:
        raise ValueError(f"Unsupported Mortal game mode: {mode!r}") from exc


def load_settings() -> Settings:
    project_root = Path(__file__).resolve().parents[1]
    runtime_root = Path(
        os.getenv("MORTAL_RUNTIME_ROOT", project_root / "_runtime")
    ).expanduser().resolve()

    # A configured unified root wins. Otherwise, automatically adopt the
    # sibling Mortal_Unified installation only after it actually exists.
    unified_env = os.getenv("MORTAL_UNIFIED_ROOT")
    default_unified = (project_root.parent / "Mortal_Unified").resolve()
    mortal_unified_root = (
        Path(unified_env).expanduser().resolve()
        if unified_env
        else default_unified if default_unified.exists() else None
    )

    # Legacy roots remain supported until the unified Windows runtime has
    # passed the real RTX smoke on the host machine.
    legacy_3p = os.getenv("MORTAL_SANMA_ROOT")
    mortal_3p_root = Path(
        os.getenv("MORTAL_3P_ROOT", legacy_3p or runtime_root / "3p")
    ).expanduser().resolve()
    mortal_4p_root = Path(
        os.getenv("MORTAL_4P_ROOT", runtime_root / "4p")
    ).expanduser().resolve()

    host = os.getenv("MORTAL_WEBUI_HOST", "127.0.0.1")
    port = int(os.getenv("MORTAL_WEBUI_PORT", "8188"))
    return Settings(
        project_root=project_root,
        mortal_3p_root=mortal_3p_root,
        mortal_4p_root=mortal_4p_root,
        host=host,
        port=port,
        runtime_root=runtime_root,
        mortal_unified_root=mortal_unified_root,
    )
