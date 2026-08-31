from __future__ import annotations

import argparse
import py_compile
from pathlib import Path


SOURCE_MARKER = "# MORTAL_ROGS_AKAGI_LEGACY_3P_BRIDGE_V1"
PATCH_MARKER = "# MORTAL_ROGS_AKAGI_LEGACY_EVENT_ADAPTER_V1"

HELPERS = r'''

# MORTAL_ROGS_AKAGI_LEGACY_EVENT_ADAPTER_V1
_UNKNOWN_HAND = ['?'] * 13


def _pad_legacy_vector(value, fill, *, field: str, event_type: str):
    if value is None:
        return None
    if not isinstance(value, list):
        raise RuntimeError(f'Akagi legacy {event_type}.{field} must be a list')
    if len(value) == 4:
        return list(value)
    if len(value) != 3:
        raise RuntimeError(
            f'Akagi legacy {event_type}.{field} expected 3 or 4 entries, got {len(value)}'
        )
    return [*value, fill]


def _normalize_legacy_event(event, player_id: int):
    if not isinstance(event, dict):
        raise RuntimeError(f'Akagi legacy MJAI event must be an object, got {type(event).__name__}')
    event = dict(event)
    event_type = str(event.get('type', ''))

    # Akagi-NG/libriichi3p keeps the historical 4-slot MJAI container ABI even
    # for sanma. Scores/deltas use a zero-valued dummy fourth seat.
    for field in ('scores', 'deltas'):
        if field in event and event[field] is not None:
            event[field] = _pad_legacy_vector(
                event[field], 0, field=field, event_type=event_type
            )

    if 'tenpais' in event and event['tenpais'] is not None:
        event['tenpais'] = _pad_legacy_vector(
            event['tenpais'], False, field='tenpais', event_type=event_type
        )

    if event_type == 'start_kyoku':
        tehais = event.get('tehais')
        if not isinstance(tehais, list) or len(tehais) not in (3, 4):
            raise RuntimeError(
                f'Akagi legacy start_kyoku.tehais expected 3 or 4 seats, got '
                f'{len(tehais) if isinstance(tehais, list) else type(tehais).__name__}'
            )
        if player_id not in (0, 1, 2):
            raise RuntimeError(f'Akagi legacy player id must be 0..2, got {player_id}')

        # The unified arena owns the full-information game log, but a Mortal
        # player must only see its own initial hand. Match Akagi-NG's bridge:
        # four 13-tile slots, opponents and the dummy fourth seat hidden.
        masked = [list(_UNKNOWN_HAND) for _ in range(4)]
        own = tehais[player_id]
        if not isinstance(own, list) or len(own) != 13:
            raise RuntimeError(
                f'Akagi legacy own start hand must contain 13 tiles, got '
                f'{len(own) if isinstance(own, list) else type(own).__name__}'
            )
        masked[player_id] = list(own)
        event['tehais'] = masked

    elif event_type == 'tsumo':
        # Full-information arena logs contain every draw. Standard MJAI only
        # reveals the bot's own draw; opponent draws must be hidden.
        actor = event.get('actor')
        if actor is not None and int(actor) != player_id:
            event['pai'] = '?'

    elif 'tehais' in event and event['tehais'] is not None:
        # Result events may carry per-seat hands. Preserve their public payload
        # while satisfying libriichi3p's four-slot container ABI.
        event['tehais'] = _pad_legacy_vector(
            event['tehais'], [], field='tehais', event_type=event_type
        )

    return event
'''


def apply(root: Path) -> None:
    root = root.expanduser().resolve()
    bridge = root / "mortal" / "akagi_legacy_3p.py"
    if not bridge.is_file():
        raise RuntimeError(f"Akagi legacy bridge is missing: {bridge}")

    text = bridge.read_text(encoding="utf-8")
    if SOURCE_MARKER not in text:
        raise RuntimeError(f"unexpected Akagi legacy bridge without managed marker: {bridge}")

    if PATCH_MARKER not in text:
        anchor = "ACTION_SPACE = 44\n"
        if text.count(anchor) != 1:
            raise RuntimeError("Akagi legacy bridge action-space anchor changed")
        text = text.replace(anchor, anchor + HELPERS, 1)

    old = "                event_json = json.dumps(event, ensure_ascii=False, separators=(',', ':'))\n"
    new = (
        "                event = _normalize_legacy_event(event, self.player_ids[game_idx])\n"
        "                event_json = json.dumps(event, ensure_ascii=False, separators=(',', ':'))\n"
    )
    if new not in text:
        if text.count(old) != 1:
            raise RuntimeError("Akagi legacy event serialization anchor changed")
        text = text.replace(old, new, 1)

    bridge.write_text(text, encoding="utf-8")
    py_compile.compile(str(bridge), doraise=True)

    post = bridge.read_text(encoding="utf-8")
    required = (
        PATCH_MARKER,
        "_normalize_legacy_event(event, self.player_ids[game_idx])",
        "masked = [list(_UNKNOWN_HAND) for _ in range(4)]",
        "event['pai'] = '?'",
        "for field in ('scores', 'deltas')",
    )
    missing = [token for token in required if token not in post]
    if missing:
        raise RuntimeError(f"Akagi legacy event adapter postcondition failed: {missing}")

    print("MORTAL_AKAGI3P_EVENT_ADAPTER_OK slots=4 hidden-info=masked")


def main() -> None:
    ap = argparse.ArgumentParser(description="Adapt unified sanma MJAI logs for Akagi legacy libriichi3p.")
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    apply(args.root)


if __name__ == "__main__":
    main()
