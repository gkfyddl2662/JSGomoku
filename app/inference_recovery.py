from __future__ import annotations

from typing import Any

from .inference_production import ProductionProfileError, normalize_serving_settings, verify_health


def target_from_active_profile(profile: dict[str, Any], *, api_key: str) -> dict[str, Any]:
    if profile.get("status") != "active":
        raise ProductionProfileError("Production profile must be active before it can be restored")
    target = profile.get("target", {}) or {}
    host = str(target.get("host", "")).strip()
    if not host:
        raise ProductionProfileError("Production profile target host is missing")
    try:
        port = int(target.get("port"))
    except (TypeError, ValueError) as exc:
        raise ProductionProfileError("Production profile target port is invalid") from exc
    if not 1 <= port <= 65535:
        raise ProductionProfileError("Production profile target port is outside 1..65535")
    device = str(target.get("device", "auto")).strip() or "auto"
    return {
        "host": host,
        "port": port,
        "device": device,
        "api_key": str(api_key),
        "serving": normalize_serving_settings(profile.get("serving")),
    }


def compare_profile_health(profile: dict[str, Any], health: dict[str, Any] | None) -> dict[str, Any]:
    if health is None:
        return {
            "verified": False,
            "matches": False,
            "drift": ["offline"],
        }
    errors = verify_health(health, profile.get("serving", {}))
    return {
        "verified": True,
        "matches": not errors,
        "drift": errors,
    }
