from __future__ import annotations

import os
import sys
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

    @property
    def models_dir(self) -> Path:
        return self.root / "models"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"


@dataclass(frozen=True)
class Settings:
    project_root: Path
    mortal_3p_root: Path
    mortal_4p_root: Path
    host: str
    port: int

    def runtime(self, mode: str) -> MortalRuntime:
        normalized = normalize_mode(mode)
        if normalized == "3p":
            mortal_dir = self.mortal_3p_root / "Mortal" / "mortal"
            config_file = mortal_dir / "config.sanma.toml"
            python_executable = self.project_root / ".venv" / "Scripts" / "python.exe"
            if os.name != "nt":
                python_executable = self.project_root / ".venv" / "bin" / "python"
            if not python_executable.exists():
                python_executable = Path(sys.executable)
            return MortalRuntime(
                mode="3p",
                players=3,
                root=self.mortal_3p_root,
                mortal_dir=mortal_dir,
                config_file=config_file,
                python_executable=python_executable,
                evaluate_script="one_vs_two.py",
            )

        mortal_dir = self.mortal_4p_root / "mortal"
        config_file = mortal_dir / "config.toml"
        python_executable = self.mortal_4p_root / ".venv" / "Scripts" / "python.exe"
        if os.name != "nt":
            python_executable = self.mortal_4p_root / ".venv" / "bin" / "python"
        return MortalRuntime(
            mode="4p",
            players=4,
            root=self.mortal_4p_root,
            mortal_dir=mortal_dir,
            config_file=config_file,
            python_executable=python_executable,
            evaluate_script="one_vs_three.py",
        )

    # Backward-compatible aliases. New code should call runtime(mode).
    @property
    def mortal_root(self) -> Path:
        return self.mortal_3p_root

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
    default_3p = project_root.parent / "Mortal_Sanma"
    default_4p = project_root.parent / "Mortal_4P"

    legacy_3p = os.getenv("MORTAL_SANMA_ROOT")
    mortal_3p_root = Path(os.getenv("MORTAL_3P_ROOT", legacy_3p or default_3p)).expanduser().resolve()
    mortal_4p_root = Path(os.getenv("MORTAL_4P_ROOT", default_4p)).expanduser().resolve()

    host = os.getenv("MORTAL_WEBUI_HOST", "127.0.0.1")
    port = int(os.getenv("MORTAL_WEBUI_PORT", "8188"))
    return Settings(
        project_root=project_root,
        mortal_3p_root=mortal_3p_root,
        mortal_4p_root=mortal_4p_root,
        host=host,
        port=port,
    )
