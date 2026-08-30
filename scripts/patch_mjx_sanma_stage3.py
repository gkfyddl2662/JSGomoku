from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


EXPECTED = {
    "include/mjx/internal/mjx.proto": "b232eee7ec94cc0369781b9f604ec3c843402067",
    "include/mjx/internal/action.h": "fe208e507d4699cf42927b72289ec4aa230928a3",
    "include/mjx/internal/action.cpp": "5d35c4a6ce6ebaee6e2f0c8a9fed3d8b9d9a8b74",
    "include/mjx/internal/event.h": "2936b253ac30a5f4617ba9e39b5712344f146a49",
    "include/mjx/internal/event.cpp": "aa2b3a0338e34360896101a2f7a7e36febd9cc96",
    "include/mjx/action.cpp": "b42de986768b1cb639c0d953c9182be625f8ed7a",
    "include/mjx/event.cpp": "b8461d5288e4a4da8ea44a145625570ac54f4766",
}


def sha(path: Path) -> str:
    return subprocess.run(
        ["git", "hash-object", str(path)], check=True, capture_output=True, text=True
    ).stdout.strip()


def replace_once(path: Path, anchor: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    if replacement in text:
        return
    count = text.count(anchor)
    if count != 1:
        raise RuntimeError(f"Expected exactly one stage-3 anchor in {path}, found {count}")
    path.write_text(text.replace(anchor, replacement, 1), encoding="utf-8")


def require_pristine(root: Path) -> None:
    # Stage 1/2 do not touch these files, so every stage-3 target must still be
    # the exact pinned v0.1.0 blob on first application.
    for rel, expected in EXPECTED.items():
        path = root / rel
        text = path.read_text(encoding="utf-8")
        if "ACTION_TYPE_NUKI" in text or "EVENT_TYPE_NUKI" in text:
            continue
        actual = sha(path)
        if actual != expected:
            raise RuntimeError(f"Unexpected upstream {rel}: expected {expected}, got {actual}")


def apply(root: Path) -> None:
    require_pristine(root)
    proto = root / "include/mjx/internal/mjx.proto"
    action_h = root / "include/mjx/internal/action.h"
    action_cpp = root / "include/mjx/internal/action.cpp"
    event_h = root / "include/mjx/internal/event.h"
    event_cpp = root / "include/mjx/internal/event.cpp"
    pub_action_cpp = root / "include/mjx/action.cpp"
    pub_event_cpp = root / "include/mjx/event.cpp"

    replace_once(
        proto,
        "  ACTION_TYPE_NO = 11;\n",
        "  ACTION_TYPE_NO = 11;\n  // Sanma: extract North tile (kita/nuki). Added without renumbering 4P values.\n  ACTION_TYPE_NUKI = 12;\n",
    )
    replace_once(
        proto,
        "  EVENT_TYPE_EXHAUSTIVE_DRAW_NAGASHI_MANGAN = 20;  // 流し満貫\n",
        "  EVENT_TYPE_EXHAUSTIVE_DRAW_NAGASHI_MANGAN = 20;  // 流し満貫\n  // Sanma-only public North extraction event.\n  EVENT_TYPE_NUKI = 21;\n",
    )
    replace_once(
        proto,
        "  // 20. EXHAUSTIVE_DRAW_NAGASHI_MANGAN  No      No      No\n",
        "  // 20. EXHAUSTIVE_DRAW_NAGASHI_MANGAN  No      No      No\n  // 21. NUKI                           Yes     Yes      No\n",
    )
    replace_once(
        proto,
        "  //  RON                Yes    No\n",
        "  //  RON                Yes    No\n  //  NUKI               Yes    No\n",
    )

    replace_once(
        action_h,
        "  static mjxproto::Action CreateRon(AbsolutePos who, Tile tile,\n                                    std::string game_id = \"\");\n",
        "  static mjxproto::Action CreateRon(AbsolutePos who, Tile tile,\n                                    std::string game_id = \"\");\n  static mjxproto::Action CreateNuki(AbsolutePos who, Tile north,\n                                     std::string game_id = \"\");\n",
    )
    replace_once(
        action_h,
        "  // 180: Dummy\n",
        "  // 180: Dummy\n  // 181: Nuki (sanma only)\n",
    )

    create_ron = '''mjxproto::Action Action::CreateRon(AbsolutePos who, Tile tile,
                                   std::string game_id) {
  mjxproto::Action proto;
  proto.set_type(mjxproto::ACTION_TYPE_RON);
  proto.set_who(ToUType(who));
  proto.set_tile((tile.Id()));
  Assert(IsValid(proto));
  return proto;
}
'''
    create_ron_nuki = create_ron + '''
mjxproto::Action Action::CreateNuki(AbsolutePos who, Tile north,
                                    std::string game_id) {
  Assert(north.Type() == TileType::kNW);
  mjxproto::Action proto;
  proto.set_type(mjxproto::ACTION_TYPE_NUKI);
  proto.set_who(ToUType(who));
  proto.set_tile(north.Id());
  Assert(IsValid(proto));
  return proto;
}
'''
    replace_once(action_cpp, create_ron, create_ron_nuki)
    replace_once(
        action_cpp,
        "    case mjxproto::ACTION_TYPE_RON:\n      if (!(0 <= action.tile() && action.tile() < 136)) return false;\n",
        "    case mjxproto::ACTION_TYPE_RON:\n    case mjxproto::ACTION_TYPE_NUKI:\n      if (!(0 <= action.tile() && action.tile() < 136)) return false;\n      if (type == mjxproto::ACTION_TYPE_NUKI && Tile(action.tile()).Type() != TileType::kNW) return false;\n",
    )
    replace_once(
        action_cpp,
        "           mjxproto::ACTION_TYPE_TSUMO, mjxproto::ACTION_TYPE_RON})) {\n",
        "           mjxproto::ACTION_TYPE_TSUMO, mjxproto::ACTION_TYPE_RON,\n           mjxproto::ACTION_TYPE_NUKI})) {\n",
    )
    replace_once(
        action_cpp,
        "    case mjxproto::ACTION_TYPE_DUMMY:\n      // 180: Dummy\n      return 180;\n",
        "    case mjxproto::ACTION_TYPE_DUMMY:\n      // 180: Dummy\n      return 180;\n    case mjxproto::ACTION_TYPE_NUKI:\n      // 181: Nuki (sanma only)\n      return 181;\n",
    )
    replace_once(
        action_cpp,
        "  } else if (event.type() == mjxproto::EVENT_TYPE_RON) {\n    proto.set_type(mjxproto::ACTION_TYPE_RON);\n    proto.set_who(event.who());\n    proto.set_tile(event.tile());\n",
        "  } else if (event.type() == mjxproto::EVENT_TYPE_RON) {\n    proto.set_type(mjxproto::ACTION_TYPE_RON);\n    proto.set_who(event.who());\n    proto.set_tile(event.tile());\n  } else if (event.type() == mjxproto::EVENT_TYPE_NUKI) {\n    proto.set_type(mjxproto::ACTION_TYPE_NUKI);\n    proto.set_who(event.who());\n    proto.set_tile(event.tile());\n",
    )

    replace_once(
        event_h,
        "  static mjxproto::Event CreateRon(AbsolutePos who, Tile tile);\n",
        "  static mjxproto::Event CreateRon(AbsolutePos who, Tile tile);\n  static mjxproto::Event CreateNuki(AbsolutePos who, Tile north);\n",
    )
    create_event_ron = '''mjxproto::Event Event::CreateRon(AbsolutePos who, Tile tile) {
  mjxproto::Event proto;
  proto.set_who(ToUType(who));
  proto.set_type(mjxproto::EVENT_TYPE_RON);
  proto.set_tile(tile.Id());
  Assert(IsValid(proto));
  return proto;
}
'''
    create_event_ron_nuki = create_event_ron + '''
mjxproto::Event Event::CreateNuki(AbsolutePos who, Tile north) {
  Assert(north.Type() == TileType::kNW);
  mjxproto::Event proto;
  proto.set_who(ToUType(who));
  proto.set_type(mjxproto::EVENT_TYPE_NUKI);
  proto.set_tile(north.Id());
  Assert(IsValid(proto));
  return proto;
}
'''
    replace_once(event_cpp, create_event_ron, create_event_ron_nuki)
    replace_once(
        event_cpp,
        "    case mjxproto::EVENT_TYPE_RON:\n      if (!mjxproto::EventType_IsValid(event.who())) return false;\n      if (!(0 <= event.tile() && event.tile() < 136)) return false;\n",
        "    case mjxproto::EVENT_TYPE_RON:\n    case mjxproto::EVENT_TYPE_NUKI:\n      if (!mjxproto::EventType_IsValid(event.who())) return false;\n      if (!(0 <= event.tile() && event.tile() < 136)) return false;\n      if (type == mjxproto::EVENT_TYPE_NUKI && Tile(event.tile()).Type() != TileType::kNW) return false;\n",
    )

    replace_once(
        pub_action_cpp,
        "           mjxproto::ACTION_TYPE_TSUMO, mjxproto::ACTION_TYPE_RON}))\n",
        "           mjxproto::ACTION_TYPE_TSUMO, mjxproto::ACTION_TYPE_RON,\n           mjxproto::ACTION_TYPE_NUKI}))\n",
    )
    replace_once(
        pub_event_cpp,
        "                   mjxproto::EVENT_TYPE_TSUMO, mjxproto::EVENT_TYPE_RON}))\n",
        "                   mjxproto::EVENT_TYPE_TSUMO, mjxproto::EVENT_TYPE_RON,\n                   mjxproto::EVENT_TYPE_NUKI}))\n",
    )

    combined = "\n".join(
        p.read_text(encoding="utf-8")
        for p in (proto, action_h, action_cpp, event_h, event_cpp, pub_action_cpp, pub_event_cpp)
    )
    for token in ("ACTION_TYPE_NUKI", "EVENT_TYPE_NUKI", "CreateNuki", "return 181"):
        if token not in combined:
            raise RuntimeError(f"Nuki protocol postcondition missing: {token}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    apply(args.root.resolve())
    print("MJX_SANMA_STAGE3_OK nuki action/event protocol")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
