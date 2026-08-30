from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .configuration import ConfigError, load_preset, merge_preset, read_toml, write_toml
from .gpu import system_status
from .jobs import JobManager
from .mortal import MortalController
from .settings import load_settings

settings = load_settings()
controller = MortalController(settings)
jobs = JobManager()
app = FastAPI(title="Mortal Sanma Control Center", version="0.1.0")
app.mount("/static", StaticFiles(directory=settings.project_root / "static"), name="static")


class ConfigBody(BaseModel):
    config: dict[str, Any]


class JobBody(BaseModel):
    kind: str
    args: dict[str, Any] = Field(default_factory=dict)


class PromoteBody(BaseModel):
    source: str
    destination: str = "best_sanma.pth"


@app.get("/")
def index() -> FileResponse:
    return FileResponse(settings.project_root / "static" / "index.html")


@app.get("/api/system")
def api_system() -> dict[str, Any]:
    return system_status()


@app.get("/api/setup/status")
def api_setup_status() -> dict[str, Any]:
    return controller.status()


@app.get("/api/config")
def api_config() -> dict[str, Any]:
    try:
        return {"path": str(settings.config_file), "config": read_toml(settings.config_file)}
    except ConfigError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.put("/api/config")
def api_config_save(body: ConfigBody) -> dict[str, Any]:
    try:
        write_toml(settings.config_file, body.config)
        return {"ok": True, "path": str(settings.config_file)}
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/config/preset/{name}")
def api_config_preset(name: str) -> dict[str, Any]:
    try:
        return load_preset(settings.project_root, name)
    except ConfigError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/config/preset/{name}/apply")
def api_apply_preset(name: str) -> dict[str, Any]:
    try:
        preset = load_preset(settings.project_root, name)
        current = read_toml(settings.config_file) if settings.config_file.exists() else {}
        merged = merge_preset(current, preset)
        write_toml(settings.config_file, merged)
        return {"ok": True, "config": merged}
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/data")
def api_data() -> dict[str, Any]:
    return controller.scan_data()


@app.get("/api/checkpoints")
def api_checkpoints() -> list[dict[str, Any]]:
    return controller.checkpoints()


@app.post("/api/checkpoints/promote")
def api_promote(body: PromoteBody) -> dict[str, str]:
    try:
        return controller.promote_checkpoint(body.source, body.destination)
    except Exception as exc:
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
