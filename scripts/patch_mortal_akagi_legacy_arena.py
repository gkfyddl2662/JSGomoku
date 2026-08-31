from __future__ import annotations

import argparse
import py_compile
from pathlib import Path


SOURCE_MARKER = "# MORTAL_ROGS_UNIFIED_EVAL_STAGE5C"
MARKER = "# MORTAL_ROGS_AKAGI_LEGACY_ARENA_V2"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        if new in text:
            return text
        raise RuntimeError(f"{label}: anchor not found")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def patch(text: str) -> str:
    if MARKER in text:
        return text
    if SOURCE_MARKER not in text:
        raise RuntimeError("Akagi legacy arena patch requires generated unified Stage 5C evaluator")

    text = replace_once(
        text,
        "from libriichi.arena import OneVsTwo\n",
        "",
        "remove eager unified arena import",
    )
    text = replace_once(
        text,
        "from akagi_legacy_3p import AkagiLegacy3PMjaiLogEngine\n",
        "from akagi_legacy_3p import AkagiLegacy3PMjaiLogEngine, _load_libriichi3p\n",
        "legacy bridge import",
    )

    text = replace_once(
        text,
        "        return _build_provider(state, state_cfg, side_cfg, default_name, obs_channels)\n\n"
        "    if obs_channels == AKAGI_LEGACY_OBS_CHANNELS:\n"
        "        provider = _build_provider(state, state_cfg, side_cfg, default_name, obs_channels)\n"
        "        return AkagiLegacy3PMjaiLogEngine(provider, str(side_cfg.get('name', default_name)))\n",
        "        return (\n"
        "            _build_provider(state, state_cfg, side_cfg, default_name, obs_channels),\n"
        "            'native-1010',\n"
        "        )\n\n"
        "    if obs_channels == AKAGI_LEGACY_OBS_CHANNELS:\n"
        "        return (\n"
        "            _build_provider(state, state_cfg, side_cfg, default_name, obs_channels),\n"
        "            'akagi-legacy-775',\n"
        "        )\n",
        "return evaluator ABI kind",
    )

    selector = r'''

# MORTAL_ROGS_AKAGI_LEGACY_ARENA_V2
def _select_arena_and_engines(
    engine_chal,
    abi_chal,
    engine_cham,
    abi_cham,
    challenger_name,
    champion_name,
):
    legacy = 'akagi-legacy-775'
    if abi_chal == legacy and abi_cham == legacy:
        lib = _load_libriichi3p()
        arena_mod = getattr(lib, 'arena', None)
        arena_cls = getattr(arena_mod, 'OneVsTwo', None) if arena_mod is not None else None
        if arena_cls is None:
            raise RuntimeError(
                'pinned Akagi libriichi3p does not expose arena.OneVsTwo; '
                'the compatibility binary is not the expected build'
            )
        print(
            'MORTAL_3P_ARENA_SELECTED source=akagi-libriichi3p '
            f'challenger_abi={abi_chal} champion_abi={abi_cham}',
            flush=True,
        )
        # The pinned 3P arena already performs the canonical 775 observation encoding,
        # so pass MortalEngine providers directly. Do not wrap them through the unified
        # 1010-state arena for legacy-vs-legacy games.
        return arena_cls, engine_chal, engine_cham

    try:
        from libriichi.arena import OneVsTwo as arena_cls
    except (ImportError, ModuleNotFoundError) as exc:
        raise RuntimeError(
            'native or mixed 3P evaluation requires unified libriichi.arena.OneVsTwo, '
            'but the installed unified runtime extension is stale; rebuild/update the '
            'Mortal_Unified libriichi extension before native-1010 or mixed evaluation'
        ) from exc

    if abi_chal == legacy:
        engine_chal = AkagiLegacy3PMjaiLogEngine(engine_chal, challenger_name)
    if abi_cham == legacy:
        engine_cham = AkagiLegacy3PMjaiLogEngine(engine_cham, champion_name)
    print(
        'MORTAL_3P_ARENA_SELECTED source=unified-libriichi '
        f'challenger_abi={abi_chal} champion_abi={abi_cham}',
        flush=True,
    )
    return arena_cls, engine_chal, engine_cham
'''

    text = replace_once(
        text,
        "\ndef main():\n",
        selector + "\n\ndef main():\n",
        "insert arena selector",
    )

    text = replace_once(
        text,
        "    engine_chal = _build_engine(challenger_state, challenger_cfg, 'challenger-3p')\n"
        "    engine_cham = _build_engine(champion_state, champion_cfg, 'champion-3p')\n",
        "    engine_chal, abi_chal = _build_engine(challenger_state, challenger_cfg, 'challenger-3p')\n"
        "    engine_cham, abi_cham = _build_engine(champion_state, champion_cfg, 'champion-3p')\n"
        "    OneVsTwo, engine_chal, engine_cham = _select_arena_and_engines(\n"
        "        engine_chal,\n"
        "        abi_chal,\n"
        "        engine_cham,\n"
        "        abi_cham,\n"
        "        str(challenger_cfg.get('name', 'challenger-3p')),\n"
        "        str(champion_cfg.get('name', 'champion-3p')),\n"
        "    )\n",
        "select arena after loading engines",
    )
    return text


def apply(root: Path) -> None:
    root = root.expanduser().resolve()
    target = root / "mortal" / "one_vs_two.py"
    if not target.is_file():
        raise RuntimeError(f"missing generated 3P evaluator: {target}")
    original = target.read_text(encoding="utf-8")
    updated = patch(original)
    if updated != original:
        target.write_text(updated, encoding="utf-8")
        print(f"patched: {target}")
    else:
        print(f"unchanged: {target}")
    py_compile.compile(str(target), doraise=True)

    post = target.read_text(encoding="utf-8")
    required = (
        MARKER,
        "source=akagi-libriichi3p",
        "source=unified-libriichi",
        "getattr(lib, 'arena', None)",
        "'akagi-legacy-775'",
        "'native-1010'",
    )
    missing = [token for token in required if token not in post]
    if missing:
        raise RuntimeError(f"Akagi legacy arena postconditions failed: {missing}")
    if "from libriichi.arena import OneVsTwo\n" in post.split(MARKER, 1)[0]:
        raise RuntimeError("eager unified arena import remains before compatibility selector")
    print("MORTAL_AKAGI_LEGACY_ARENA_V2_OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    apply(args.root)


if __name__ == "__main__":
    main()
