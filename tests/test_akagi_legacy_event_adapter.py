from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from scripts.patch_mortal_akagi_legacy_events import PATCH_MARKER, apply


BRIDGE_STUB = '''from __future__ import annotations
import json

# MORTAL_ROGS_AKAGI_LEGACY_3P_BRIDGE_V1
ACTION_SPACE = 44

class Stub:
    def __init__(self):
        self.player_ids = [1]

    def feed(self, event, game_idx=0):
        event_json = json.dumps(event, ensure_ascii=False, separators=(',', ':'))
        return event_json
'''


def _load(path: Path):
    name = f"_akagi_legacy_event_adapter_test_{abs(hash(str(path)))}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_legacy_event_adapter_masks_hidden_information_and_pads_slots(tmp_path: Path) -> None:
    mortal = tmp_path / "mortal"
    mortal.mkdir()
    bridge = mortal / "akagi_legacy_3p.py"
    bridge.write_text(BRIDGE_STUB, encoding="utf-8")

    apply(tmp_path)
    text = bridge.read_text(encoding="utf-8")
    assert PATCH_MARKER in text
    assert "_normalize_legacy_event(event, self.player_ids[game_idx])" in text

    module = _load(bridge)
    normalize = module._normalize_legacy_event

    hands = [
        [f"A{i}" for i in range(13)],
        [f"B{i}" for i in range(13)],
        [f"C{i}" for i in range(13)],
    ]
    start = normalize(
        {
            "type": "start_kyoku",
            "scores": [35000, 35000, 35000],
            "tehais": hands,
        },
        1,
    )
    assert start["scores"] == [35000, 35000, 35000, 0]
    assert start["tehais"][1] == hands[1]
    assert start["tehais"][0] == ["?"] * 13
    assert start["tehais"][2] == ["?"] * 13
    assert start["tehais"][3] == ["?"] * 13

    opponent_draw = normalize({"type": "tsumo", "actor": 0, "pai": "9s"}, 1)
    own_draw = normalize({"type": "tsumo", "actor": 1, "pai": "9s"}, 1)
    assert opponent_draw["pai"] == "?"
    assert own_draw["pai"] == "9s"

    hora = normalize(
        {
            "type": "hora",
            "scores": [40000, 35000, 30000],
            "deltas": [5000, -3000, -2000],
        },
        1,
    )
    assert hora["scores"] == [40000, 35000, 30000, 0]
    assert hora["deltas"] == [5000, -3000, -2000, 0]

    ryukyoku = normalize(
        {
            "type": "ryukyoku",
            "scores": [35000, 35000, 35000],
            "tenpais": [True, False, True],
            "tehais": [["1p"], [], ["9s"]],
        },
        1,
    )
    assert ryukyoku["scores"] == [35000, 35000, 35000, 0]
    assert ryukyoku["tenpais"] == [True, False, True, False]
    assert ryukyoku["tehais"] == [["1p"], [], ["9s"], []]


def test_legacy_event_adapter_is_idempotent(tmp_path: Path) -> None:
    mortal = tmp_path / "mortal"
    mortal.mkdir()
    bridge = mortal / "akagi_legacy_3p.py"
    bridge.write_text(BRIDGE_STUB, encoding="utf-8")

    apply(tmp_path)
    first = bridge.read_text(encoding="utf-8")
    apply(tmp_path)
    second = bridge.read_text(encoding="utf-8")
    assert first == second
