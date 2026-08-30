from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Job:
    id: str
    kind: str
    command: list[str]
    cwd: str
    started_at: float
    process: subprocess.Popen[str]
    lines: deque[str] = field(default_factory=lambda: deque(maxlen=4000))
    ended_at: float | None = None
    returncode: int | None = None

    def snapshot(self, include_logs: bool = False) -> dict[str, Any]:
        running = self.process.poll() is None
        if not running and self.ended_at is None:
            self.ended_at = time.time()
            self.returncode = self.process.returncode
        out = {
            "id": self.id,
            "kind": self.kind,
            "command": self.command,
            "cwd": self.cwd,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "running": running,
            "returncode": self.returncode,
        }
        if include_logs:
            out["logs"] = list(self.lines)
        return out


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, kind: str, command: list[str], cwd: Path, env: dict[str, str] | None = None) -> Job:
        if not cwd.exists():
            raise FileNotFoundError(f"Working directory does not exist: {cwd}")

        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        merged_env.setdefault("PYTHONUNBUFFERED", "1")

        flags = 0
        if os.name == "nt":
            flags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]

        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=merged_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=flags,
            start_new_session=os.name != "nt",
        )
        job = Job(
            id=uuid.uuid4().hex[:12],
            kind=kind,
            command=command,
            cwd=str(cwd),
            started_at=time.time(),
            process=process,
        )
        with self._lock:
            self._jobs[job.id] = job
        threading.Thread(target=self._pump, args=(job,), daemon=True).start()
        return job

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            jobs = list(self._jobs.values())
        return [j.snapshot() for j in sorted(jobs, key=lambda x: x.started_at, reverse=True)]

    def get(self, job_id: str, include_logs: bool = True) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            raise KeyError(job_id)
        return job.snapshot(include_logs=include_logs)

    def stop(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            raise KeyError(job_id)
        if job.process.poll() is not None:
            return job.snapshot(include_logs=True)

        # Inference serving owns a graceful drain path in its shutdown handler.
        # Give uvicorn/Python a real termination signal first so already-accepted
        # Akagi requests can complete before falling back to a hard process-tree kill.
        graceful_inference = job.kind == "inference_api"
        wait_timeout = 8.0 if graceful_inference else 5.0

        if os.name == "nt":
            if graceful_inference:
                try:
                    job.process.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
                    job.process.wait(timeout=wait_timeout)
                    return job.snapshot(include_logs=True)
                except (ValueError, OSError, subprocess.TimeoutExpired):
                    pass
            subprocess.run(
                ["taskkill", "/PID", str(job.process.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                check=False,
            )
        else:
            try:
                os.killpg(os.getpgid(job.process.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass

        try:
            job.process.wait(timeout=wait_timeout)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                job.process.kill()
            else:
                try:
                    os.killpg(os.getpgid(job.process.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    job.process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    job.process.kill()
        return job.snapshot(include_logs=True)

    @staticmethod
    def _pump(job: Job) -> None:
        assert job.process.stdout is not None
        for line in job.process.stdout:
            job.lines.append(line.rstrip("\r\n"))
        job.process.wait()
        job.returncode = job.process.returncode
        job.ended_at = time.time()
