from __future__ import annotations

import json
import sys


def main() -> int:
    try:
        import mjx
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"import mjx failed: {exc}"}, ensure_ascii=False, indent=2))
        return 2

    result: dict[str, object] = {
        "ok": True,
        "python": sys.version.split()[0],
        "mjx_version": getattr(mjx, "__version__", "unknown"),
    }

    try:
        env = mjx.MjxEnv()
        obs = env.reset(seed=1)
        players = sorted(obs.keys())
        result["players"] = players
        result["player_count"] = len(players)
        if len(players) != 4:
            raise RuntimeError(f"expected upstream MJX 4P environment, got {len(players)} players")
        first_obs = next(iter(obs.values()))
        result["legal_actions"] = len(first_obs.legal_actions())
        result["has_action_mask"] = hasattr(first_obs, "action_mask")
        result["has_events"] = hasattr(first_obs, "events")
    except Exception as exc:
        result["ok"] = False
        result["error"] = f"MJX environment smoke test failed: {exc}"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 3

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
