from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class GameModeSpec:
    mode: str
    players: int
    action_space: int
    obs_channels_v4: int
    oracle_obs_channels_v4: int
    grp_size: int
    allow_chi: bool
    allow_nuki: bool
    checkpoint_name: str

    @property
    def obs_shape_v4(self) -> tuple[int, int]:
        return self.obs_channels_v4, 34

    @property
    def oracle_obs_shape_v4(self) -> tuple[int, int]:
        return self.oracle_obs_channels_v4, 34


def normalize_mode(mode: str | None) -> str:
    value = (mode or "4p").strip().casefold()
    aliases = {
        "3": "3p",
        "3p": "3p",
        "sanma": "3p",
        "4": "4p",
        "4p": "4p",
        "yonma": "4p",
    }
    try:
        return aliases[value]
    except KeyError as exc:
        raise ValueError(f"unsupported game mode: {mode!r}") from exc


@lru_cache(maxsize=1)
def _manifest() -> dict:
    path = Path(__file__).resolve().parents[1] / "mortal_unified" / "manifest.toml"
    with path.open("rb") as f:
        return tomllib.load(f)


def game_mode_spec(mode: str | None) -> GameModeSpec:
    normalized = normalize_mode(mode)
    cfg = _manifest()["modes"][normalized]
    return GameModeSpec(
        mode=normalized,
        players=int(cfg["players"]),
        action_space=int(cfg["action_space"]),
        obs_channels_v4=int(cfg["obs_channels_v4"]),
        oracle_obs_channels_v4=int(cfg["oracle_obs_channels_v4"]),
        grp_size=int(cfg["grp_size"]),
        allow_chi=bool(cfg["allow_chi"]),
        allow_nuki=bool(cfg["allow_nuki"]),
        checkpoint_name=str(cfg["checkpoint_name"]),
    )
