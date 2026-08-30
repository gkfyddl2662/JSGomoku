from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    project_root: Path
    mortal_root: Path
    host: str
    port: int

    @property
    def mortal_dir(self) -> Path:
        return self.mortal_root / "Mortal" / "mortal"

    @property
    def config_file(self) -> Path:
        return self.mortal_dir / "config.sanma.toml"

    @property
    def models_dir(self) -> Path:
        return self.mortal_root / "models"

    @property
    def data_dir(self) -> Path:
        return self.mortal_root / "data"

    @property
    def runs_dir(self) -> Path:
        return self.mortal_root / "runs"


def load_settings() -> Settings:
    project_root = Path(__file__).resolve().parents[1]
    default_mortal = project_root.parent / "Mortal_Sanma"
    mortal_root = Path(os.getenv("MORTAL_SANMA_ROOT", default_mortal)).expanduser().resolve()
    host = os.getenv("MORTAL_WEBUI_HOST", "127.0.0.1")
    port = int(os.getenv("MORTAL_WEBUI_PORT", "8188"))
    return Settings(project_root=project_root, mortal_root=mortal_root, host=host, port=port)
