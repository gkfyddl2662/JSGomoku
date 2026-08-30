from __future__ import annotations

import importlib.util
import sys
import threading
import tomllib
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any


@dataclass(frozen=True, slots=True)
class ModeContract:
    mode: str
    players: int
    action_space: int
    obs_channels: int
    oracle_obs_channels: int


_CONTRACTS = {
    "3p": ModeContract("3p", 3, 44, 1010, 170),
    "4p": ModeContract("4p", 4, 46, 1012, 217),
}

_MODULE_CACHE: dict[Path, ModuleType] = {}
_MODULE_LOCK = threading.Lock()


def contract_for(mode: str) -> ModeContract:
    normalized = mode.strip().casefold()
    aliases = {"3": "3p", "sanma": "3p", "3p": "3p", "4": "4p", "yonma": "4p", "4p": "4p"}
    try:
        return _CONTRACTS[aliases[normalized]]
    except KeyError as exc:
        raise ValueError(f"Unsupported Mortal API mode: {mode!r}") from exc


def _runtime_model_module(mortal_dir: Path) -> ModuleType:
    mortal_dir = mortal_dir.resolve()
    with _MODULE_LOCK:
        cached = _MODULE_CACHE.get(mortal_dir)
        if cached is not None:
            return cached

        model_py = mortal_dir / "model.py"
        if not model_py.is_file():
            raise FileNotFoundError(f"Unified Mortal model.py not found: {model_py}")

        # Use a path-specific module name so a legacy/runtime `model` import in the
        # control process cannot silently contaminate the serving ABI.
        module_name = f"_mortal_rogs_runtime_model_{abs(hash(str(model_py)))}"
        spec = importlib.util.spec_from_file_location(module_name, model_py)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not load Mortal model module: {model_py}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        _MODULE_CACHE[mortal_dir] = module
        return module


def resolve_checkpoint_path(runtime_root: Path, mode: str, explicit: Path | None = None) -> Path:
    root = runtime_root.expanduser().resolve()
    contract = contract_for(mode)
    models_dir = root / "runtime" / contract.mode / "models"

    if explicit is not None:
        candidate = explicit.expanduser()
        if not candidate.is_absolute():
            candidate = models_dir / candidate
        return candidate.resolve()

    config_path = root / "mortal" / f"config.{contract.mode}.toml"
    if config_path.is_file():
        with config_path.open("rb") as f:
            cfg = tomllib.load(f)
        configured = cfg.get("control", {}).get("best_state_file")
        if isinstance(configured, str) and configured.strip():
            candidate = Path(configured).expanduser()
            if not candidate.is_absolute():
                candidate = models_dir / candidate
            return candidate.resolve()

    return (models_dir / "best_mortal.pth").resolve()


def _validate_checkpoint_config(cfg: dict[str, Any], contract: ModeContract) -> tuple[int, int]:
    control = cfg.get("control")
    resnet = cfg.get("resnet")
    if not isinstance(control, dict) or not isinstance(resnet, dict):
        raise ValueError("Checkpoint config must contain [control] and [resnet]")

    version = int(control.get("version", -1))
    if version != 4:
        raise ValueError(f"Mortal API serves the v4 ABI only; checkpoint is v{version}")

    game = cfg.get("game")
    if isinstance(game, dict):
        if "mode" in game and contract_for(str(game["mode"])).mode != contract.mode:
            raise ValueError(f"Checkpoint game mode {game['mode']!r} does not match endpoint {contract.mode}")
        if "num_players" in game and int(game["num_players"]) != contract.players:
            raise ValueError("Checkpoint player-count ABI mismatch")
        if "action_space" in game and int(game["action_space"]) != contract.action_space:
            raise ValueError("Checkpoint action-space ABI mismatch")
        if "obs_channels" in game and int(game["obs_channels"]) != contract.obs_channels:
            raise ValueError("Checkpoint observation ABI mismatch")

    conv_channels = int(resnet["conv_channels"])
    num_blocks = int(resnet["num_blocks"])
    if conv_channels <= 0 or num_blocks < 0:
        raise ValueError("Invalid ResNet checkpoint configuration")
    return conv_channels, num_blocks


class LoadedModel:
    def __init__(self, mode: str, model_path: Path, mortal_dir: Path, device: str) -> None:
        self.contract = contract_for(mode)
        self.path = model_path.resolve()
        self._infer_lock = threading.RLock()

        import torch

        self.torch = torch
        requested = device.strip().casefold()
        if requested == "auto":
            requested = "cuda:0" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(requested)
        if self.device.type == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA inference was requested but torch.cuda.is_available() is false")

        state = torch.load(self.path, map_location="cpu", weights_only=False)
        if not isinstance(state, dict):
            raise ValueError("Mortal checkpoint root must be a mapping")
        for key in ("config", "mortal", "current_dqn"):
            if key not in state:
                raise ValueError(f"Mortal checkpoint missing required key: {key}")
        cfg = state["config"]
        if not isinstance(cfg, dict):
            raise ValueError("Checkpoint config must be a mapping")

        conv_channels, num_blocks = _validate_checkpoint_config(cfg, self.contract)
        model_module = _runtime_model_module(mortal_dir)
        Brain = getattr(model_module, "Brain")
        DQN = getattr(model_module, "DQN")
        brain = Brain(
            version=4,
            conv_channels=conv_channels,
            num_blocks=num_blocks,
            obs_channels=self.contract.obs_channels,
        ).eval()
        dqn = DQN(version=4, action_space=self.contract.action_space).eval()
        brain.load_state_dict(state["mortal"], strict=True)
        dqn.load_state_dict(state["current_dqn"], strict=True)
        self.brain = brain.to(self.device)
        self.dqn = dqn.to(self.device)
        self.config = cfg

        # Probe the exact endpoint ABI before publishing this model into the slot.
        with self._infer_lock, torch.inference_mode():
            obs = torch.zeros((1, self.contract.obs_channels, 34), dtype=torch.float32, device=self.device)
            mask = torch.ones((1, self.contract.action_space), dtype=torch.bool, device=self.device)
            q = self.dqn(self.brain(obs), mask)
        if tuple(q.shape) != (1, self.contract.action_space):
            raise ValueError(f"Checkpoint inference shape mismatch: {tuple(q.shape)}")
        if not bool(torch.isfinite(q).all()):
            raise ValueError("Checkpoint probe produced non-finite legal Q values")

    def infer(self, obs: Any, masks: Any) -> dict[str, Any]:
        torch = self.torch
        obs_t = torch.as_tensor(obs, dtype=torch.float32, device=self.device)
        masks_t = torch.as_tensor(masks, dtype=torch.bool, device=self.device)
        if obs_t.ndim != 3 or tuple(obs_t.shape[1:]) != (self.contract.obs_channels, 34):
            raise ValueError(
                f"{self.contract.mode} obs must be [batch,{self.contract.obs_channels},34], got {tuple(obs_t.shape)}"
            )
        if masks_t.ndim != 2 or masks_t.shape[0] != obs_t.shape[0] or masks_t.shape[1] != self.contract.action_space:
            raise ValueError(
                f"{self.contract.mode} masks must be [batch,{self.contract.action_space}], got {tuple(masks_t.shape)}"
            )
        if obs_t.shape[0] <= 0:
            raise ValueError("Inference batch must be non-empty")
        if not bool(masks_t.any(dim=1).all()):
            raise ValueError("Every inference row must contain at least one legal action")

        # Uvicorn normally serializes this synchronous GPU work in one event loop,
        # but keep the model itself safe when embedded in tests or multi-threaded hosts.
        with self._infer_lock, torch.inference_mode():
            q = self.dqn(self.brain(obs_t), masks_t)
        if tuple(q.shape) != (obs_t.shape[0], self.contract.action_space):
            raise RuntimeError(f"Unexpected Q output shape: {tuple(q.shape)}")
        legal_q = q[masks_t]
        if legal_q.numel() == 0 or not bool(torch.isfinite(legal_q).all()):
            raise RuntimeError("Mortal inference produced non-finite legal Q values")

        actions = q.argmax(dim=-1)
        # Keep the HTTP response valid JSON. Akagi also receives the legal mask,
        # so a finite sentinel for illegal actions preserves decision semantics.
        safe_q = q.masked_fill(~masks_t, -1.0e9)
        return {
            "actions": actions.detach().cpu().tolist(),
            "q_out": safe_q.detach().float().cpu().tolist(),
            "masks": masks_t.detach().cpu().tolist(),
            "is_greedy": [True] * int(obs_t.shape[0]),
        }


class ModelSlot:
    def __init__(self, mode: str, path: Path, mortal_dir: Path, device: str) -> None:
        self.contract = contract_for(mode)
        self.path = path.resolve()
        self.mortal_dir = mortal_dir.resolve()
        self.device = device
        self._lock = threading.RLock()
        self._loaded: LoadedModel | None = None
        self._loaded_signature: tuple[int, int] | None = None
        self._failed_signature: tuple[int, int] | None = None
        self._last_error: str | None = None

    def _signature(self) -> tuple[int, int]:
        st = self.path.stat()
        return st.st_mtime_ns, st.st_size

    def get(self) -> LoadedModel:
        with self._lock:
            if not self.path.is_file():
                self._last_error = f"FileNotFoundError: {self.contract.mode} API model not found: {self.path}"
                if self._loaded is not None:
                    return self._loaded
                raise FileNotFoundError(f"{self.contract.mode} API model not found: {self.path}")

            signature = self._signature()
            if self._loaded is not None and signature == self._loaded_signature:
                return self._loaded
            if self._loaded is not None and signature == self._failed_signature:
                return self._loaded

            try:
                loaded = LoadedModel(self.contract.mode, self.path, self.mortal_dir, self.device)
            except Exception as exc:
                self._failed_signature = signature
                self._last_error = f"{type(exc).__name__}: {exc}"
                if self._loaded is not None:
                    return self._loaded
                raise

            self._loaded = loaded
            self._loaded_signature = signature
            self._failed_signature = None
            self._last_error = None
            return loaded

    def status(self) -> dict[str, Any]:
        with self._lock:
            current_signature = self._signature() if self.path.is_file() else None
            return {
                "mode": self.contract.mode,
                "path": str(self.path),
                "exists": self.path.is_file(),
                "loaded": self._loaded is not None,
                "current": current_signature == self._loaded_signature if current_signature is not None else False,
                "last_error": self._last_error,
                "action_space": self.contract.action_space,
                "obs_shape": [self.contract.obs_channels, 34],
            }


class InferenceService:
    def __init__(
        self,
        runtime_root: Path,
        *,
        device: str = "auto",
        model_3p: Path | None = None,
        model_4p: Path | None = None,
    ) -> None:
        self.runtime_root = runtime_root.expanduser().resolve()
        mortal_dir = self.runtime_root / "mortal"
        if not mortal_dir.is_dir():
            raise FileNotFoundError(f"Unified Mortal directory not found: {mortal_dir}")
        self.slots = {
            "3p": ModelSlot("3p", resolve_checkpoint_path(self.runtime_root, "3p", model_3p), mortal_dir, device),
            "4p": ModelSlot("4p", resolve_checkpoint_path(self.runtime_root, "4p", model_4p), mortal_dir, device),
        }

    def infer(self, mode: str, obs: Any, masks: Any) -> dict[str, Any]:
        contract = contract_for(mode)
        return self.slots[contract.mode].get().infer(obs, masks)

    def health(self) -> dict[str, Any]:
        models = {mode: slot.status() for mode, slot in self.slots.items()}
        degraded = any((not info["exists"]) or info["last_error"] is not None for info in models.values())
        return {
            "ok": True,
            "degraded": degraded,
            "protocol": "akagiot-v1",
            "runtime_root": str(self.runtime_root),
            "endpoints": {"3p": "/react_batch_3p", "4p": "/react_batch"},
            "models": models,
        }
