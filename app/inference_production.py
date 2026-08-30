from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SOAK_PROTOCOL = "mortal-rogs-serving-soak-v1"
PROFILE_PROTOCOL = "mortal-rogs-serving-profile-v1"

DEFAULT_SERVING = {
    "micro_batch_ms": 1.0,
    "micro_batch_max_rows": 64,
    "max_pending_requests": 128,
    "request_deadline_ms": 3500.0,
    "reload_poll_ms": 500.0,
    "max_device_executions": 1,
    "reload_quiet_ms": 150.0,
    "reload_wait_ms": 1000.0,
    "drain_timeout_ms": 3500.0,
}

SERVING_FIELDS = tuple(DEFAULT_SERVING)


class ProductionProfileError(RuntimeError):
    pass


class ProductionApplyError(RuntimeError):
    def __init__(self, message: str, *, rollback: dict[str, Any]) -> None:
        super().__init__(message)
        self.rollback = rollback


@dataclass
class LifecycleOps:
    drain: Callable[[float], dict[str, Any]]
    stop: Callable[[], dict[str, Any]]
    start: Callable[[dict[str, Any]], dict[str, Any]]
    wait_healthy: Callable[[dict[str, Any], float], dict[str, Any]]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_serving_settings(values: dict[str, Any] | None) -> dict[str, Any]:
    source = dict(values or {})
    out = dict(DEFAULT_SERVING)
    for key in SERVING_FIELDS:
        if key in source:
            out[key] = source[key]

    out["micro_batch_ms"] = float(out["micro_batch_ms"])
    out["micro_batch_max_rows"] = int(out["micro_batch_max_rows"])
    out["max_pending_requests"] = int(out["max_pending_requests"])
    out["request_deadline_ms"] = float(out["request_deadline_ms"])
    out["reload_poll_ms"] = float(out["reload_poll_ms"])
    out["max_device_executions"] = int(out["max_device_executions"])
    out["reload_quiet_ms"] = float(out["reload_quiet_ms"])
    out["reload_wait_ms"] = float(out["reload_wait_ms"])
    out["drain_timeout_ms"] = float(out["drain_timeout_ms"])

    if not 0.0 <= out["micro_batch_ms"] <= 100.0:
        raise ProductionProfileError("micro_batch_ms must be between 0 and 100")
    if not 1 <= out["micro_batch_max_rows"] <= 4096:
        raise ProductionProfileError("micro_batch_max_rows must be between 1 and 4096")
    if not 1 <= out["max_pending_requests"] <= 4096:
        raise ProductionProfileError("max_pending_requests must be between 1 and 4096")
    if not 0.0 < out["request_deadline_ms"] < 4000.0:
        raise ProductionProfileError("request_deadline_ms must stay below AkagiOT's 4s read timeout")
    if not 50.0 <= out["reload_poll_ms"] <= 60000.0:
        raise ProductionProfileError("reload_poll_ms must be between 50 and 60000")
    if out["max_device_executions"] != 1:
        raise ProductionProfileError("RTX 5080 production profile requires max_device_executions=1")
    if not 0.0 <= out["reload_quiet_ms"] <= 10000.0:
        raise ProductionProfileError("reload_quiet_ms must be between 0 and 10000")
    if not 0.0 < out["reload_wait_ms"] <= 60000.0:
        raise ProductionProfileError("reload_wait_ms must be between 0 and 60000")
    if not 0.0 < out["drain_timeout_ms"] <= 60000.0:
        raise ProductionProfileError("drain_timeout_ms must be between 0 and 60000")
    return out


def latest_eligible_soak(runtime_root: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    report_dir = runtime_root / "runtime" / "serving-benchmarks"
    files = sorted(
        (path for path in report_dir.glob("soak-*.json") if path.is_file()),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    ) if report_dir.is_dir() else []
    if not files:
        raise ProductionProfileError("No serving soak report exists")

    latest = files[0]
    try:
        report = json.loads(latest.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductionProfileError(f"Latest soak report is unreadable: {exc}") from exc
    if not isinstance(report, dict) or report.get("protocol") != SOAK_PROTOCOL:
        raise ProductionProfileError("Latest soak report has an unexpected schema")

    gate = report.get("production_gate", {}) or {}
    preset = report.get("production_preset", {}) or {}
    if gate.get("passed") is not True or gate.get("validation_level") != "production":
        raise ProductionProfileError("Latest soak report did not pass the production gate")
    if preset.get("eligible") is not True or not isinstance(preset.get("settings"), dict):
        raise ProductionProfileError("Latest soak report does not contain an eligible production preset")

    serving = normalize_serving_settings(preset["settings"])
    return latest, report, serving


def build_profile(
    target: dict[str, Any],
    serving: dict[str, Any],
    *,
    source_report: Path,
    source_payload: dict[str, Any],
    status: str = "applying",
) -> dict[str, Any]:
    return {
        "protocol": PROFILE_PROTOCOL,
        "status": status,
        "updated_at": utc_now(),
        "target": {
            "host": str(target.get("host", "127.0.0.1")),
            "port": int(target.get("port", 8190)),
            "device": str(target.get("device", "auto")),
        },
        "serving": normalize_serving_settings(serving),
        "source": {
            "report": str(source_report),
            "soak_protocol": source_payload.get("protocol"),
            "elapsed_s": source_payload.get("elapsed_s"),
            "production_gate": source_payload.get("production_gate"),
            "gpu": source_payload.get("gpu"),
        },
    }


def profile_path(runtime_root: Path) -> Path:
    return runtime_root / "runtime" / "serving-profiles" / "production.json"


def _atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def atomic_write_profile(path: Path, payload: dict[str, Any]) -> None:
    raw = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _atomic_write(path, raw)


def snapshot_profile(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def restore_profile(path: Path, previous: bytes | None) -> None:
    if previous is None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    _atomic_write(path, previous)


def read_profile(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductionProfileError(f"Production profile is unreadable: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("protocol") != PROFILE_PROTOCOL:
        raise ProductionProfileError("Production profile has an unexpected schema")
    return payload


def _equal_number(actual: Any, expected: float | int, tolerance: float = 1.0e-6) -> bool:
    try:
        return abs(float(actual) - float(expected)) <= tolerance
    except (TypeError, ValueError):
        return False


def verify_health(health: dict[str, Any], serving: dict[str, Any]) -> list[str]:
    expected = normalize_serving_settings(serving)
    errors: list[str] = []
    if health.get("protocol") != "akagiot-v1":
        errors.append("protocol")
    if health.get("degraded") is True:
        errors.append("degraded")

    lifecycle = health.get("lifecycle", {}) or {}
    if lifecycle.get("state") != "running" or lifecycle.get("accepting") is not True:
        errors.append("lifecycle")

    for mode in ("3p", "4p"):
        model = health.get("models", {}).get(mode, {}) or {}
        if model.get("loaded") is not True or model.get("current") is not True or model.get("last_error") is not None:
            errors.append(f"model:{mode}")

    live = health.get("serving", {}) or {}
    micro = live.get("micro_batch", {}) or {}
    reload_cfg = live.get("reload", {}) or {}
    device = live.get("device_scheduler", {}) or {}

    checks = {
        "micro_batch_ms": (micro.get("wait_ms"), expected["micro_batch_ms"]),
        "micro_batch_max_rows": (micro.get("max_rows"), expected["micro_batch_max_rows"]),
        "max_pending_requests": (micro.get("max_pending_requests"), expected["max_pending_requests"]),
        "request_deadline_ms": (micro.get("request_deadline_ms"), expected["request_deadline_ms"]),
        "reload_poll_ms": (reload_cfg.get("poll_ms"), expected["reload_poll_ms"]),
        "reload_quiet_ms": (reload_cfg.get("quiet_ms"), expected["reload_quiet_ms"]),
        "reload_wait_ms": (reload_cfg.get("wait_ms"), expected["reload_wait_ms"]),
        "max_device_executions": (device.get("max_parallel_executions"), expected["max_device_executions"]),
        "drain_timeout_ms": (live.get("drain_timeout_ms"), expected["drain_timeout_ms"]),
    }
    for name, (actual, wanted) in checks.items():
        if not _equal_number(actual, wanted):
            errors.append(name)
    return errors


def apply_profile_transaction(
    *,
    path: Path,
    candidate_profile: dict[str, Any],
    previous_target: dict[str, Any],
    candidate_target: dict[str, Any],
    ops: LifecycleOps,
    verify_timeout_s: float,
) -> dict[str, Any]:
    previous_bytes = snapshot_profile(path)
    events: list[dict[str, Any]] = []
    atomic_write_profile(path, candidate_profile)
    events.append({"stage": "profile_saved", "ok": True})

    try:
        drain_timeout = float(normalize_serving_settings(previous_target.get("serving"))["drain_timeout_ms"])
        drain = ops.drain(drain_timeout)
        events.append({"stage": "drain", "ok": bool(drain.get("drained")), "detail": drain})
        if drain.get("drained") is not True:
            raise ProductionProfileError(f"Graceful drain did not complete: {drain}")

        stopped = ops.stop()
        events.append({"stage": "stop", "ok": True, "detail": stopped})
        started = ops.start(candidate_target)
        events.append({"stage": "start_candidate", "ok": True, "detail": started})
        health = ops.wait_healthy(candidate_target, verify_timeout_s)
        errors = verify_health(health, candidate_target.get("serving", {}))
        if errors:
            raise ProductionProfileError(f"Candidate health verification failed: {', '.join(errors)}")

        active_profile = dict(candidate_profile)
        active_profile["status"] = "active"
        active_profile["activated_at"] = utc_now()
        active_profile["updated_at"] = active_profile["activated_at"]
        atomic_write_profile(path, active_profile)
        events.append({"stage": "verified", "ok": True})
        return {
            "ok": True,
            "rolled_back": False,
            "profile": active_profile,
            "health": health,
            "events": events,
        }
    except Exception as apply_exc:
        rollback: dict[str, Any] = {"attempted": True, "ok": False, "events": []}
        try:
            try:
                stopped = ops.stop()
                rollback["events"].append({"stage": "stop_candidate", "ok": True, "detail": stopped})
            except Exception as stop_exc:
                rollback["events"].append(
                    {"stage": "stop_candidate", "ok": False, "error": f"{type(stop_exc).__name__}: {stop_exc}"}
                )

            restore_profile(path, previous_bytes)
            rollback["events"].append({"stage": "profile_restored", "ok": True})
            started = ops.start(previous_target)
            rollback["events"].append({"stage": "restart_previous", "ok": True, "detail": started})
            health = ops.wait_healthy(previous_target, verify_timeout_s)
            errors = verify_health(health, previous_target.get("serving", {}))
            if errors:
                raise ProductionProfileError(f"Rollback health verification failed: {', '.join(errors)}")
            rollback["ok"] = True
            rollback["health"] = health
        except Exception as rollback_exc:
            rollback["error"] = f"{type(rollback_exc).__name__}: {rollback_exc}"

        raise ProductionApplyError(
            f"{type(apply_exc).__name__}: {apply_exc}",
            rollback=rollback,
        ) from apply_exc
