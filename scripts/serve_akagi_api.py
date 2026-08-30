from __future__ import annotations

import argparse
import gzip
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from serving.coordination import CoordinatedInferenceService, InferenceDrainingError
from serving.inference import contract_for
from serving.resilient import (
    InferenceBusyError,
    InferenceDeadlineExceeded,
    ResilientInferenceService,
)


AKAGI_READ_TIMEOUT_MS = 4000.0


def parse_args() -> argparse.Namespace:
    default_root = Path(os.getenv("MORTAL_UNIFIED_ROOT", PROJECT_ROOT.parent / "Mortal_Unified"))
    p = argparse.ArgumentParser(
        description="Serve unified Mortal 3P/4P checkpoints through Akagi-NG's existing AkagiOT HTTP protocol."
    )
    p.add_argument("--runtime-root", type=Path, default=default_root)
    p.add_argument("--host", default=os.getenv("MORTAL_INFERENCE_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.getenv("MORTAL_INFERENCE_PORT", "8190")))
    p.add_argument("--device", default=os.getenv("MORTAL_INFERENCE_DEVICE", "auto"))
    p.add_argument("--api-key", default=os.getenv("MORTAL_INFERENCE_API_KEY", ""))
    p.add_argument("--model-3p", type=Path, default=None)
    p.add_argument("--model-4p", type=Path, default=None)
    p.add_argument(
        "--micro-batch-ms",
        type=float,
        default=float(os.getenv("MORTAL_INFERENCE_MICRO_BATCH_MS", "1.0")),
        help="Maximum coalescing window for concurrent same-mode requests.",
    )
    p.add_argument(
        "--micro-batch-max-rows",
        type=int,
        default=int(os.getenv("MORTAL_INFERENCE_MICRO_BATCH_MAX_ROWS", "64")),
    )
    p.add_argument(
        "--max-pending-requests",
        type=int,
        default=int(os.getenv("MORTAL_INFERENCE_MAX_PENDING_REQUESTS", "128")),
    )
    p.add_argument(
        "--request-deadline-ms",
        type=float,
        default=float(os.getenv("MORTAL_INFERENCE_REQUEST_DEADLINE_MS", "3500")),
        help="Server-side deadline. Must stay below pinned AkagiOT's 4s read timeout.",
    )
    p.add_argument(
        "--reload-poll-ms",
        type=float,
        default=float(os.getenv("MORTAL_INFERENCE_RELOAD_POLL_MS", "500")),
        help="Background checkpoint change polling interval.",
    )
    p.add_argument(
        "--max-device-executions",
        type=int,
        default=int(os.getenv("MORTAL_INFERENCE_MAX_DEVICE_EXECUTIONS", "1")),
        help="Maximum simultaneous 3P/4P model forwards on the shared device.",
    )
    p.add_argument(
        "--reload-quiet-ms",
        type=float,
        default=float(os.getenv("MORTAL_INFERENCE_RELOAD_QUIET_MS", "150")),
        help="Required device-idle window before hot-reload begins.",
    )
    p.add_argument(
        "--reload-wait-ms",
        type=float,
        default=float(os.getenv("MORTAL_INFERENCE_RELOAD_WAIT_MS", "1000")),
        help="Maximum explicit reload wait for a quiet device window.",
    )
    p.add_argument(
        "--drain-timeout-ms",
        type=float,
        default=float(os.getenv("MORTAL_INFERENCE_DRAIN_TIMEOUT_MS", "3500")),
        help="Default graceful drain window before process shutdown.",
    )
    return p.parse_args()


def _decode_json(raw: bytes, encoding: str | None) -> dict[str, Any]:
    if encoding and encoding.casefold() == "gzip":
        try:
            raw = gzip.decompress(raw)
        except OSError as exc:
            raise HTTPException(400, f"Invalid gzip request body: {exc}") from exc
    if not raw:
        return {}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(400, f"Invalid JSON request body: {exc}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(400, "Request JSON root must be an object")
    return payload


def _decode_payload(raw: bytes, encoding: str | None) -> dict[str, Any]:
    payload = _decode_json(raw, encoding)
    if "obs" not in payload or "masks" not in payload:
        raise HTTPException(400, "Request must contain obs and masks")
    return payload


def _model_identity(info: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(info["path"]))
    return {
        "name": path.name,
        "path": str(path),
        "checkpoint_signature": info.get("loaded_signature"),
        "candidate_signature": info.get("candidate_signature"),
        "abi_version": 4,
        "device": info.get("device"),
        "compiled": info.get("compiled"),
        "amp_dtype": info.get("amp_dtype"),
        "current": info.get("current"),
        "reloading": info.get("reloading"),
    }


def create_app(service: CoordinatedInferenceService, api_key: str = "") -> FastAPI:
    app = FastAPI(title="Mortal-ROGS Inference API", version="1.5.0")
    expected_key = api_key.strip()

    def authorize(request: Request) -> None:
        if not expected_key:
            return
        supplied = request.headers.get("Authorization", "")
        if supplied != expected_key:
            raise HTTPException(401, "Invalid API key")

    async def infer_request(request: Request, mode: str, *, detailed: bool) -> dict[str, Any]:
        authorize(request)
        try:
            contract = contract_for(mode)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        payload = _decode_payload(await request.body(), request.headers.get("Content-Encoding"))
        started = time.perf_counter()
        try:
            response = await run_in_threadpool(service.infer, contract.mode, payload["obs"], payload["masks"])
        except (InferenceBusyError, InferenceDeadlineExceeded, InferenceDrainingError) as exc:
            raise HTTPException(503, str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(503, str(exc)) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(500, f"Mortal inference failed: {type(exc).__name__}: {exc}") from exc

        if not detailed:
            return response

        latency_ms = (time.perf_counter() - started) * 1000.0
        info = service.slots[contract.mode].status()
        response = dict(response)
        response.update(
            {
                "mode": contract.mode,
                "action_space": contract.action_space,
                "obs_shape": [contract.obs_channels, 34],
                "latency_ms": round(latency_ms, 3),
                "model": _model_identity(info),
                "protocol": "mortal-rogs-inference-v1",
            }
        )
        if len(response.get("actions", [])) == 1:
            response["selected_action"] = response["actions"][0]
        return response

    @app.on_event("shutdown")
    def shutdown_service() -> None:
        service.close()

    @app.get("/health")
    def health(request: Request) -> dict[str, Any]:
        authorize(request)
        return service.health()

    @app.post("/react_batch")
    async def react_batch(request: Request) -> dict[str, Any]:
        return await infer_request(request, "4p", detailed=False)

    @app.post("/react_batch_3p")
    async def react_batch_3p(request: Request) -> dict[str, Any]:
        return await infer_request(request, "3p", detailed=False)

    @app.get("/api/inference/health")
    def managed_health(request: Request) -> dict[str, Any]:
        authorize(request)
        result = dict(service.health())
        result["management_protocol"] = "mortal-rogs-inference-v1"
        return result

    @app.get("/api/inference/models")
    def managed_models(request: Request) -> dict[str, Any]:
        authorize(request)
        health_state = service.health()
        models = {
            mode: {**info, "model": _model_identity(info)}
            for mode, info in health_state["models"].items()
        }
        return {
            "ok": True,
            "degraded": health_state["degraded"],
            "protocol": "mortal-rogs-inference-v1",
            "models": models,
        }

    @app.get("/api/inference/metrics")
    def managed_metrics(request: Request) -> dict[str, Any]:
        authorize(request)
        return service.metrics()

    @app.post("/api/inference/tuning")
    async def managed_tuning(request: Request) -> dict[str, Any]:
        authorize(request)
        payload = _decode_json(await request.body(), request.headers.get("Content-Encoding"))
        unknown = set(payload) - {"micro_batch_ms"}
        if unknown:
            raise HTTPException(400, f"Unsupported live tuning fields: {', '.join(sorted(unknown))}")
        if "micro_batch_ms" not in payload:
            raise HTTPException(400, "micro_batch_ms is required")
        value = payload["micro_batch_ms"]
        if isinstance(value, bool):
            raise HTTPException(400, "micro_batch_ms must be numeric")
        try:
            tuning = service.set_micro_batch_wait(float(value))
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return {
            "ok": True,
            "protocol": "mortal-rogs-inference-v1",
            "live": True,
            "models_reloaded": False,
            "micro_batch": tuning,
        }

    @app.post("/api/inference/drain")
    async def managed_drain(request: Request) -> dict[str, Any]:
        authorize(request)
        payload = _decode_json(await request.body(), request.headers.get("Content-Encoding"))
        timeout_ms = payload.get("timeout_ms", service.drain_timeout_ms)
        if isinstance(timeout_ms, bool):
            raise HTTPException(400, "timeout_ms must be numeric")
        try:
            timeout_ms = float(timeout_ms)
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "timeout_ms must be numeric") from exc
        if not 0.0 <= timeout_ms <= 10000.0:
            raise HTTPException(400, "timeout_ms must be between 0 and 10000")
        result = await run_in_threadpool(service.drain, timeout_ms)
        return {
            "ok": bool(result.get("drained")),
            "protocol": "mortal-rogs-inference-v1",
            "drain": result,
        }

    @app.post("/api/inference/reload")
    async def managed_reload(request: Request) -> dict[str, Any]:
        authorize(request)
        payload = _decode_json(await request.body(), request.headers.get("Content-Encoding"))
        requested_mode = payload.get("mode")
        if requested_mode is None:
            modes = ("3p", "4p")
        elif isinstance(requested_mode, str):
            try:
                modes = (contract_for(requested_mode).mode,)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
        else:
            raise HTTPException(400, "reload mode must be a string when supplied")

        results: dict[str, Any] = {}
        for mode in modes:
            result = await run_in_threadpool(service.reload, mode)
            if result.get("ok"):
                info = result["status"]
                results[mode] = {"ok": True, "status": info, "model": _model_identity(info)}
            else:
                results[mode] = result

        ok = all(bool(result.get("ok")) for result in results.values())
        if not ok:
            raise HTTPException(409, detail={"ok": False, "results": results})
        return {"ok": True, "protocol": "mortal-rogs-inference-v1", "results": results}

    @app.post("/api/inference/{mode}")
    async def managed_inference(mode: str, request: Request) -> dict[str, Any]:
        return await infer_request(request, mode, detailed=True)

    return app


def _is_loopback(host: str) -> bool:
    return host.strip().casefold() in {"127.0.0.1", "localhost", "::1"}


def main() -> int:
    args = parse_args()
    if not 1 <= args.port <= 65535:
        raise SystemExit("--port must be between 1 and 65535")
    if not _is_loopback(args.host) and not args.api_key.strip():
        raise SystemExit("Refusing to expose Mortal inference beyond loopback without --api-key")
    if args.micro_batch_ms < 0:
        raise SystemExit("--micro-batch-ms must be >= 0")
    if args.micro_batch_max_rows < 1:
        raise SystemExit("--micro-batch-max-rows must be >= 1")
    if args.max_pending_requests < 1:
        raise SystemExit("--max-pending-requests must be >= 1")
    if not 0 < args.request_deadline_ms < AKAGI_READ_TIMEOUT_MS:
        raise SystemExit(
            f"--request-deadline-ms must be >0 and <{AKAGI_READ_TIMEOUT_MS:.0f}ms "
            "to fail before pinned AkagiOT's read timeout"
        )
    if args.reload_poll_ms < 50:
        raise SystemExit("--reload-poll-ms must be >= 50")
    if args.max_device_executions < 1:
        raise SystemExit("--max-device-executions must be >= 1")
    if args.reload_quiet_ms < 0 or args.reload_wait_ms < 0:
        raise SystemExit("--reload-quiet-ms and --reload-wait-ms must be >= 0")
    if not 0 < args.drain_timeout_ms < AKAGI_READ_TIMEOUT_MS:
        raise SystemExit(
            f"--drain-timeout-ms must be >0 and <{AKAGI_READ_TIMEOUT_MS:.0f}ms "
            "to complete before pinned AkagiOT's read timeout"
        )

    base_service = ResilientInferenceService(
        args.runtime_root,
        device=args.device,
        model_3p=args.model_3p,
        model_4p=args.model_4p,
        micro_batch_ms=args.micro_batch_ms,
        micro_batch_max_rows=args.micro_batch_max_rows,
        max_pending_requests=args.max_pending_requests,
        request_deadline_ms=args.request_deadline_ms,
        reload_poll_ms=args.reload_poll_ms,
    )
    service = CoordinatedInferenceService(
        base_service,
        max_device_executions=args.max_device_executions,
        reload_quiet_ms=args.reload_quiet_ms,
        reload_wait_ms=args.reload_wait_ms,
        drain_timeout_ms=args.drain_timeout_ms,
    )

    print("MORTAL_AKAGI_API_WARMUP_BEGIN", flush=True)
    try:
        warmup = service.warmup()
    except Exception as exc:
        service.close()
        raise SystemExit(f"Mortal Akagi API warmup failed: {type(exc).__name__}: {exc}") from exc
    service.start_background()
    print("MORTAL_AKAGI_API_WARMUP_OK " + json.dumps(warmup, ensure_ascii=False), flush=True)

    app = create_app(service, args.api_key)
    print(
        f"MORTAL_AKAGI_API_START root={service.runtime_root} host={args.host} port={args.port} "
        f"device={args.device} auth={'on' if args.api_key.strip() else 'off'} "
        f"micro_batch_ms={args.micro_batch_ms} max_rows={args.micro_batch_max_rows} "
        f"pending={args.max_pending_requests} deadline_ms={args.request_deadline_ms} "
        f"reload_poll_ms={args.reload_poll_ms} max_device_executions={args.max_device_executions} "
        f"reload_quiet_ms={args.reload_quiet_ms} reload_wait_ms={args.reload_wait_ms} "
        f"drain_timeout_ms={args.drain_timeout_ms}",
        flush=True,
    )

    config = uvicorn.Config(app, host=args.host, port=args.port, reload=False, access_log=False)
    server = uvicorn.Server(config)
    if os.name == "nt" and hasattr(signal, "SIGBREAK"):
        # Control Center starts inference in CREATE_NEW_PROCESS_GROUP and sends
        # CTRL_BREAK_EVENT on stop/restart. Translate SIGBREAK into Uvicorn's
        # normal graceful-exit path so lifespan shutdown can drain/close models.
        def handle_sigbreak(_signum: int, _frame: Any) -> None:
            server.should_exit = True

        signal.signal(signal.SIGBREAK, handle_sigbreak)
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
