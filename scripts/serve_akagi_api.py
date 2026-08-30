from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import uvicorn
from fastapi import FastAPI, HTTPException, Request

from serving.inference import InferenceService, contract_for


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
    signature = None
    if path.is_file():
        stat = path.stat()
        signature = f"{stat.st_mtime_ns}:{stat.st_size}"
    return {
        "name": path.name,
        "path": str(path),
        "checkpoint_signature": signature,
        "abi_version": 4,
        "device": info.get("device"),
        "compiled": info.get("compiled"),
        "amp_dtype": info.get("amp_dtype"),
        "current": info.get("current"),
    }


def create_app(service: InferenceService, api_key: str = "") -> FastAPI:
    app = FastAPI(title="Mortal-ROGS Inference API", version="1.2.0")
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
            response = service.infer(contract.mode, payload["obs"], payload["masks"])
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

    @app.get("/health")
    def health(request: Request) -> dict[str, Any]:
        """AkagiOT-compatible health endpoint kept for existing clients."""
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
            slot = service.slots[mode]
            try:
                slot.get()
            except Exception as exc:
                results[mode] = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "status": slot.status()}
                continue
            info = slot.status()
            ok = bool(info["loaded"] and info["current"] and info["last_error"] is None)
            results[mode] = {"ok": ok, "status": info, "model": _model_identity(info)}

        ok = all(result["ok"] for result in results.values())
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

    service = InferenceService(
        args.runtime_root,
        device=args.device,
        model_3p=args.model_3p,
        model_4p=args.model_4p,
    )

    # Load, strict-validate, compile (when requested), and execute one real forward
    # pass before uvicorn binds the socket. AkagiOT uses a 5-second request timeout;
    # it must never be the process that pays the first torch.compile cost.
    print("MORTAL_AKAGI_API_WARMUP_BEGIN", flush=True)
    try:
        warmup = service.warmup()
    except Exception as exc:
        raise SystemExit(f"Mortal Akagi API warmup failed: {type(exc).__name__}: {exc}") from exc
    print("MORTAL_AKAGI_API_WARMUP_OK " + json.dumps(warmup, ensure_ascii=False), flush=True)

    app = create_app(service, args.api_key)
    print(
        f"MORTAL_AKAGI_API_START root={service.runtime_root} host={args.host} port={args.port} "
        f"device={args.device} auth={'on' if args.api_key.strip() else 'off'}",
        flush=True,
    )
    uvicorn.run(app, host=args.host, port=args.port, reload=False, access_log=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
