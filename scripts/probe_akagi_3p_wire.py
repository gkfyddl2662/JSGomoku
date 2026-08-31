from __future__ import annotations

import json


class CaptureEngine:
    """Minimal Akagi/Mortal engine contract that records the real Bot tensors."""

    name = "akagi-3p-wire-probe"
    is_oracle = False
    version = 4
    enable_quick_eval = False
    enable_rule_based_agari_guard = True
    engine_type = "akagiot"

    def __init__(self) -> None:
        self.observations: list[tuple[int, int, int]] = []

    def react_batch(self, obs, masks, invisible_obs=None):
        rows = len(obs)
        if rows <= 0 or len(masks) != rows:
            raise RuntimeError("Akagi wire probe received an invalid batch")

        obs_channels = len(obs[0])
        obs_tiles = len(obs[0][0])
        action_space = len(masks[0])
        self.observations.append((obs_channels, obs_tiles, action_space))

        actions: list[int] = []
        clean_masks: list[list[bool]] = []
        for row in masks:
            clean = [bool(value) for value in row]
            try:
                action = clean.index(True)
            except ValueError as exc:
                raise RuntimeError("Akagi wire probe received a row with no legal action") from exc
            actions.append(action)
            clean_masks.append(clean)

        return (
            actions,
            [[0.0] * action_space for _ in range(rows)],
            clean_masks,
            [True] * rows,
        )


def _event(kind: str, **kwargs) -> str:
    return json.dumps({"type": kind, **kwargs}, ensure_ascii=False, separators=(",", ":"))


def main() -> int:
    import libriichi3p

    if tuple(libriichi3p.consts.obs_shape(4)) != (775, 34):
        raise SystemExit(f"Pinned libriichi3p const contract changed: {libriichi3p.consts.obs_shape(4)}")
    if int(libriichi3p.consts.ACTION_SPACE) != 44:
        raise SystemExit(f"Pinned libriichi3p action contract changed: {libriichi3p.consts.ACTION_SPACE}")

    engine = CaptureEngine()
    bot = libriichi3p.mjai.Bot(engine, 0)
    bot.react(_event("start_game"))

    unknown = ["?"] * 13
    bot.react(
        _event(
            "start_kyoku",
            bakaze="E",
            dora_marker="1s",
            kyoku=1,
            honba=0,
            kyotaku=0,
            oya=0,
            scores=[35000, 35000, 35000, 0],
            tehais=[
                ["1p", "2p", "3p", "4p", "5p", "6p", "7p", "8p", "9p", "1s", "2s", "3s", "E"],
                unknown,
                unknown,
                unknown,
            ],
        )
    )
    response = bot.react(_event("tsumo", actor=0, pai="4s"))
    if not response:
        raise SystemExit("Pinned libriichi3p Bot produced no response to the probe tsumo")
    if not engine.observations:
        raise SystemExit("Pinned libriichi3p Bot never invoked the engine")
    if any(shape != (775, 34, 44) for shape in engine.observations):
        raise SystemExit(f"Unexpected real Akagi 3P wire tensor(s): {engine.observations}")

    print(
        "AKAGI_PINNED_3P_WIRE_PROBE_OK",
        "obs=775x34",
        "actions=44",
        f"calls={len(engine.observations)}",
        f"response={response}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
