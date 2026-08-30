from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .configuration import ConfigError, load_preset, merge_preset, read_toml, write_toml
from .evaluation import evaluation_status
from .gpu import system_status
from .jobs import JobManager
from .mortal import MortalController
from .settings import load_settings, normalize_mode

settings = load_settings()
controller = MortalController(settings)
jobs = JobManager()
app = FastAPI(title="Mortal ROGS Control Center", version="0.6.0")
app.mount("/static", StaticFiles(directory=settings.project_root / "static"), name="static")

# The inference server is a separate process. Remember the most recently launched
# bind target and job so the Control Center can manage its full lifecycle without
# ever handing Mortal checkpoint files to Akagi-NG.
_inference_target: dict[str, Any] = {"host": "127.0.0.1", "port": 8190}
_inference_job_id: str | None = None


class ConfigBody(BaseModel):
    config: dict[str, Any]


class JobBody(BaseModel):
    kind: str
    args: dict[str, Any] = Field(default_factory=dict)


class InferenceBody(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=8190, ge=1, le=65535)
    api_key: str = "mortal-rogs-local"
    device: str = "auto"


class PromotionBody(BaseModel):
    source: str
    destination: str = "best_mortal.pth"
    paired_results: str
    profile: str
    mode: str = "3p"


def _runtime(mode: str):
    try:
        return settings.runtime(normalize_mode(mode))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _under(path: Path, root: Path) -> Path:
    path = path.resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise HTTPException(400, "Path escapes the allowed runtime directory") from exc
    return path


def _probe_inference_health(host: str, port: int) -> dict[str, Any]:
    normalized = host.strip().casefold()
    # 0.0.0.0/:: are valid bind addresses but not useful connect targets.
    connect_host = "127.0.0.1" if normalized in {"", "0.0.0.0", "::", "[::]"} else host.strip()
    url = f"http://{connect_host}:{port}/health"
    try:
        with urllib.request.urlopen(url, timeout=0.6) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return {"running": True, "url": f"http://{host}:{port}", "health_url": url, "health": payload, "error": None}
    except (OSError, urllib.error.URLError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {"running": False, "url": f"http://{host}:{port}", "health_url": url, "health": None, "error": str(exc)}


def _inference_job_snapshot() -> dict[str, Any] | None:
    if _inference_job_id is None:
        return None
    try:
        return jobs.get(_inference_job_id, include_logs=False)
    except KeyError:
        return None


@app.get("/")
def index() -> FileResponse:
    return FileResponse(settings.project_root / "static" / "index.html")


@app.get("/api/system")
def api_system() -> dict[str, Any]:
    return system_status()


@app.get("/api/setup/status")
def api_setup_status(mode: str = "3p") -> dict[str, Any]:
    try:
        return controller.status(mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/setup/status/all")
def api_setup_status_all() -> dict[str, Any]:
    return controller.all_statuses()


@app.get("/api/evaluation/backends")
def api_evaluation_backends() -> dict[str, Any]:
    try:
        return evaluation_status(settings.project_root)
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@app.get("/api/inference/status")
def api_inference_status() -> dict[str, Any]:
    r3 = _runtime("3p")
    r4 = _runtime("4p")
    unified = bool(r3.unified and r4.unified and r3.root == r4.root and r3.python_executable == r4.python_executable)
    host = str(_inference_target["host"])
    port = int(_inference_target["port"])
    live = _probe_inference_health(host, port) if unified else {"running": False, "health": None, "error": "unified runtime unavailable"}
    return {
        "unified": unified,
        "runtime_root": str(r3.root) if unified else None,
        "python": str(r3.python_executable) if unified else None,
        "default_url": "http://127.0.0.1:8190",
        "server_url": f"http://{host}:{port}",
        "live": live,
        "job": _inference_job_snapshot(),
        "endpoints": {"3p": "/react_batch_3p", "4p": "/react_batch"},
        "best_models": {
            "3p": str(r3.models_dir / "best_mortal.pth"),
            "4p": str(r4.models_dir / "best_mortal.pth"),
        },
        "akagi_settings": {
            "ot": {
                "online": True,
                "server": f"http://{host}:{port}",
                "api_key": "<same API key configured in Mortal-ROGS>",
            }
        },
    }


@app.post("/api/inference/start")
def api_inference_start(body: InferenceBody) -> dict[str, Any]:
    global _inference_job_id

    r3 = _runtime("3p")
    r4 = _runtime("4p")
    if not (r3.unified and r4.unified and r3.root == r4.root and r3.python_executable == r4.python_executable):
        raise HTTPException(400, "Akagi API serving requires the unified Mortal runtime")
    if not r3.python_executable.is_file():
        raise HTTPException(400, f"Unified Python runtime is missing: {r3.python_executable}")
    script = settings.project_root / "scripts" / "serve_akagi_api.py"
    if not script.is_file():
        raise HTTPException(500, f"Inference API script is missing: {script}")

    # Make Start idempotent from the user perspective: starting again replaces the
    # Control-Center-managed API process instead of creating a port-conflicting job.
    previous = _inference_job_snapshot()
    if previous and previous.get("running"):
        jobs.stop(str(previous["id"]))

    host = body.host.strip() or "127.0.0.1"
    cmd = [
        str(r3.python_executable),
        str(script),
        "--runtime-root",
        str(r3.root),
        "--host",
        host,
        "--port",
        str(body.port),
        "--device",
        body.device.strip() or "auto",
    ]
    if body.api_key:
        cmd.extend(["--api-key", body.api_key])
    try:
        job = jobs.start("inference_api", cmd, settings.project_root, controller._mortal_env(r3))
        _inference_target["host"] = host
        _inference_target["port"] = body.port
        _inference_job_id = job.id
        return job.snapshot()
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/inference/stop")
def api_inference_stop() -> dict[str, Any]:
    global _inference_job_id

    snapshot = _inference_job_snapshot()
    if snapshot is None:
        return {"ok": True, "stopped": False, "reason": "no Control-Center-managed inference API job"}
    try:
        stopped = jobs.stop(str(snapshot["id"]))
    except KeyError:
        _inference_job_id = None
        return {"ok": True, "stopped": False, "reason": "inference API job no longer exists"}
    _inference_job_id = None
    return {"ok": True, "stopped": True, "job": stopped}


@app.post("/api/promotion/start")
def api_promotion_start(body: PromotionBody) -> dict[str, Any]:
    runtime = _runtime(body.mode)
    source = _under(runtime.models_dir / body.source, runtime.models_dir)
    destination = _under(runtime.models_dir / body.destination, runtime.models_dir)
    if not source.is_file() or source.suffix.casefold() != ".pth":
        raise HTTPException(400, f"Candidate checkpoint must be an existing .pth file: {source}")
    if destination.suffix.casefold() != ".pth":
        raise HTTPException(400, "Promotion destination must end with .pth")

    paired = Path(body.paired_results).expanduser().resolve()
    if not paired.is_file() or paired.suffix.casefold() not in {".json", ".jsonl"}:
        raise HTTPException(400, "Paired evaluation results must be an existing JSON/JSONL file")
    profile = body.profile.strip()
    if not profile:
        raise HTTPException(400, "A rating profile is required")

    report_dir = runtime.runs_dir / "promotion"
    report_dir.mkdir(parents=True, exist_ok=True)
    report = report_dir / f"{source.stem}-{runtime.mode}-{profile}.json"
    script = settings.project_root / "scripts" / "promote_if_passed.py"
    cmd = [
        str(runtime.python_executable),
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
        runtime.mode,
        "--runtime-root",
        str(runtime.root),
        "--report",
        str(report),
    ]
    try:
        job = jobs.start("promote_gated", cmd, settings.project_root, controller._mortal_env(runtime))
        return job.snapshot()
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/config")
def api_config(mode: str = "3p") -> dict[str, Any]:
    runtime = _runtime(mode)
    try:
        return {
            "mode": runtime.mode,
            "path": str(runtime.config_file),
            "config": read_toml(runtime.config_file),
        }
    except ConfigError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.put("/api/config")
def api_config_save(body: ConfigBody, mode: str = "3p") -> dict[str, Any]:
    runtime = _runtime(mode)
    try:
        write_toml(runtime.config_file, body.config)
        return {"ok": True, "mode": runtime.mode, "path": str(runtime.config_file)}
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/config/preset/{name}")
def api_config_preset(name: str, mode: str = "3p") -> dict[str, Any]:
    runtime = _runtime(mode)
    try:
        return {"mode": runtime.mode, "preset": load_preset(settings.project_root, name, runtime.mode)}
    except ConfigError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/config/preset/{name}/apply")
def api_apply_preset(name: str, mode: str = "3p") -> dict[str, Any]:
    runtime = _runtime(mode)
    try:
        preset = load_preset(settings.project_root, name, runtime.mode)
        current = read_toml(runtime.config_file) if runtime.config_file.exists() else {}
        merged = merge_preset(current, preset)
        write_toml(runtime.config_file, merged)
        return {"ok": True, "mode": runtime.mode, "config": merged}
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/data")
def api_data(mode: str = "3p") -> dict[str, Any]:
    try:
        return controller.scan_data(mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/checkpoints")
def api_checkpoints(mode: str = "3p") -> list[dict[str, Any]]:
    try:
        return controller.checkpoints(mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/jobs")
def api_jobs() -> list[dict[str, Any]]:
    return jobs.list()


@app.get("/api/jobs/{job_id}")
def api_job(job_id: str) -> dict[str, Any]:
    try:
        return jobs.get(job_id)
    except KeyError as exc:
        raise HTTPException(404, "Job not found") from exc


@app.post("/api/jobs")
def api_start_job(body: JobBody) -> dict[str, Any]:
    try:
        cmd, cwd, env = controller.command_for(body.kind, body.args)
        job = jobs.start(body.kind, cmd, cwd, env)
        return job.snapshot()
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/jobs/{job_id}/stop")
def api_stop_job(job_id: str) -> dict[str, Any]:
    try:
        return jobs.stop(job_id)
    except KeyError as exc:
        raise HTTPException(404, "Job not found") from exc


def run() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    run()
