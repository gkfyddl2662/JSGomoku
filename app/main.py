from __future__ import annotations

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
app = FastAPI(title="Mortal ROGS Control Center", version="0.4.0")
app.mount("/static", StaticFiles(directory=settings.project_root / "static"), name="static")


class ConfigBody(BaseModel):
    config: dict[str, Any]


class JobBody(BaseModel):
    kind: str
    args: dict[str, Any] = Field(default_factory=dict)


def _runtime(mode: str):
    try:
        return settings.runtime(normalize_mode(mode))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


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
