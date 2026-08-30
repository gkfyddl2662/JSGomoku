from __future__ import annotations

import argparse
import shutil
from pathlib import Path


MARKER = "MORTAL_ROGS_UNIFIED_ABI_TEST_STAGE3F"
REQUIRES = "MORTAL_ROGS_UNIFIED_ACTION_OBS_STAGE3E"

TESTS = r'''

// MORTAL_ROGS_UNIFIED_ABI_TEST_STAGE3F
fn unified_v4_test_hand() -> Vec<crate::tile::Tile> {
    vec![
        t!(1m), t!(9m),
        t!(1p), t!(2p), t!(3p), t!(6p), t!(7p), t!(8p),
        t!(1s), t!(2s), t!(3s),
        t!(E), t!(S),
    ]
}

fn unified_start_kyoku(num_players: usize) -> Event {
    let start_score = if num_players == 3 { 35_000 } else { 25_000 };
    Event::StartKyoku {
        bakaze: t!(E),
        dora_marker: t!(4p),
        kyoku: 1,
        honba: 0,
        kyotaku: 0,
        oya: 0,
        scores: vec![start_score; num_players],
        tehais: (0..num_players).map(|_| unified_v4_test_hand()).collect(),
    }
}

#[test]
fn unified_v4_sanma_nukidora_abi() {
    let mut ps = PlayerState::new(0);
    ps.update(&unified_start_kyoku(3)).unwrap();
    assert_eq!(ps.num_players, 3);
    assert_eq!(ps.tiles_left, 55);

    ps.update(&Event::Tsumo {
        actor: 0,
        pai: t!(N),
    })
    .unwrap();

    assert!(ps.last_cans.can_discard);
    assert!(ps.last_cans.can_nukidora);
    assert!(!ps.last_cans.can_chi());

    let (obs, mask) = ps.encode_obs(4, false);
    assert_eq!(obs.dim(), (1010, 34));
    assert_eq!(mask.len(), 44);
    assert!(mask[38], "3P action 38 must be nukidora");

    let nuki = Event::Nukidora {
        actor: 0,
        pai: t!(N),
    };
    ps.validate_reaction(&nuki).unwrap();
    ps.update(&nuki).unwrap();

    assert_eq!(ps.tehai[tuz!(N)], 0);
    assert_eq!(ps.doras_owned[0], 1);
    assert!(ps.at_rinshan);
    assert!(!ps.last_cans.can_discard);
    assert!(!ps.last_cans.can_nukidora);

    ps.update(&Event::Tsumo {
        actor: 0,
        pai: t!(9s),
    })
    .unwrap();
    assert!(ps.last_cans.can_discard);
    assert!(ps.at_rinshan);

    let (obs, mask) = ps.encode_obs(4, false);
    assert_eq!(obs.dim(), (1010, 34));
    assert_eq!(mask.len(), 44);
}

#[test]
fn unified_v4_yonma_keeps_stock_abi_and_rejects_nukidora() {
    let mut ps = PlayerState::new(0);
    ps.update(&unified_start_kyoku(4)).unwrap();
    assert_eq!(ps.num_players, 4);
    assert_eq!(ps.tiles_left, 70);

    ps.update(&Event::Tsumo {
        actor: 0,
        pai: t!(N),
    })
    .unwrap();

    assert!(!ps.last_cans.can_nukidora);
    let (obs, mask) = ps.encode_obs(4, false);
    assert_eq!(obs.dim(), (1012, 34));
    assert_eq!(mask.len(), 46);

    let illegal_nuki = Event::Nukidora {
        actor: 0,
        pai: t!(N),
    };
    assert!(ps.validate_reaction(&illegal_nuki).is_err());
}
'''


def replace_exact(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def normalize_stock_tests(text: str) -> str:
    scores_old = "        scores: [25000; 4],\n"
    scores_count = text.count(scores_old)
    if scores_count == 2:
        text = text.replace(scores_old, "        scores: vec![25000; 4],\n")
    elif scores_count != 0:
        raise RuntimeError(f"stock score fixtures: expected 0 or 2 anchors, found {scores_count}")

    text = replace_exact(
        text,
        '''        tehais: [
            tile37_to_vec(&hand_with_aka("23406m 456789p 58s").unwrap())
                .try_into()
                .unwrap(),
            [t!(?); 13],
            [t!(?); 13],
            [t!(?); 13],
        ],
''',
        '''        tehais: vec![
            tile37_to_vec(&hand_with_aka("23406m 456789p 58s").unwrap()),
            vec![t!(?); 13],
            vec![t!(?); 13],
            vec![t!(?); 13],
        ],
''',
        "furiten StartKyoku fixture",
    )
    text = replace_exact(
        text,
        '''        tehais: [
            tile37_to_vec(&hand_with_aka("1111s 123456p 112z").unwrap())
                .try_into()
                .unwrap(),
            [t!(?); 13],
            [t!(?); 13],
            [t!(?); 13],
        ],
''',
        '''        tehais: vec![
            tile37_to_vec(&hand_with_aka("1111s 123456p 112z").unwrap()),
            vec![t!(?); 13],
            vec![t!(?); 13],
            vec![t!(?); 13],
        ],
''',
        "dora-count StartKyoku fixture",
    )
    return text


def apply(root: Path) -> None:
    obs = root / "libriichi/src/state/obs_repr.rs"
    if not obs.is_file() or REQUIRES not in obs.read_text(encoding="utf-8"):
        raise RuntimeError("Stage 3F requires Stage 3E")

    path = root / "libriichi/src/state/test.rs"
    if not path.is_file():
        raise RuntimeError(f"missing state tests: {path}")

    original = path.read_text(encoding="utf-8")
    updated = normalize_stock_tests(original)
    if MARKER not in updated:
        updated = updated.rstrip() + TESTS.rstrip() + "\n"

    if updated != original:
        backup = path.with_suffix(path.suffix + ".unified-stage3f.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(updated, encoding="utf-8")
        print(f"patched: {path}")
    else:
        print(f"unchanged: {path}")

    post = path.read_text(encoding="utf-8")
    required = (
        MARKER,
        "scores: vec![25000; 4]",
        "unified_v4_sanma_nukidora_abi",
        "obs.dim(), (1010, 34)",
        "mask.len(), 44",
        "unified_v4_yonma_keeps_stock_abi_and_rejects_nukidora",
        "obs.dim(), (1012, 34)",
        "mask.len(), 46",
    )
    missing = [needle for needle in required if needle not in post]
    if missing:
        raise RuntimeError(f"Stage 3F postconditions failed: {missing}")

    print("MORTAL_UNIFIED_ABI_TEST_STAGE3F_OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    apply(args.root.expanduser().resolve())


if __name__ == "__main__":
    main()
