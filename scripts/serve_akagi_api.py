from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import uvicorn
from fastapi import FastAPI, HTTPException, Request

from serving.inference import InferenceService


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


def _decode_payload(raw: bytes, encoding: str | None) -> dict[str, Any]:
    if encoding and encoding.casefold() == "gzip":
        try:
            raw = gzip.decompress(raw)
        except OSError as exc:
            raise HTTPException(400, f"Invalid gzip request body: {exc}") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(400, f"Invalid JSON request body: {exc}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(400, "Request JSON root must be an object")
    if "obs" not in payload or "masks" not in payload:
        raise HTTPException(400, "Request must contain obs and masks")
    return payload


def create_app(service: InferenceService, api_key: str = "") -> FastAPI:
    app = FastAPI(title="Mortal-ROGS Akagi Inference API", version="1.0.0")
    expected_key = api_key.strip()

    def authorize(request: Request) -> None:
        if not expected_key:
            return
        supplied = request.headers.get("Authorization", "")
        if supplied != expected_key:
            raise HTTPException(401, "Invalid API key")

    async def react(request: Request, mode: str) -> dict[str, Any]:
        authorize(request)
        payload = _decode_payload(await request.body(), request.headers.get("Content-Encoding"))
        try:
            return service.infer(mode, payload["obs"], payload["masks"])
        except FileNotFoundError as exc:
            raise HTTPException(503, str(exc)) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(500, f"Mortal inference failed: {type(exc).__name__}: {exc}") from exc

    @app.get("/health")
    def health() -> dict[str, Any]:
        return service.health()

    @app.post("/react_batch")
    async def react_batch(request: Request) -> dict[str, Any]:
        return await react(request, "4p")

    @app.post("/react_batch_3p")
    async def react_batch_3p(request: Request) -> dict[str, Any]:
        return await react(request, "3p")

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
    app = create_app(service, args.api_key)
    print(
        f"MORTAL_AKAGI_API_START root={service.runtime_root} host={args.host} port={args.port} "
        f"device={args.device} auth={'on' if args.api_key.strip() else 'off'}"
    )
    uvicorn.run(app, host=args.host, port=args.port, reload=False, access_log=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
