from __future__ import annotations

import argparse
import py_compile
import re
from pathlib import Path

MARKER = "# MORTAL_ROGS_UNIFIED_PYTHON_ABI_STAGE8A"
IMPORT_RE = re.compile(
    r"^(?P<indent>[ \t]*)from libriichi\.(?P<submodule>[A-Za-z_][A-Za-z0-9_]*) import (?P<names>[^\n]+)$",
    re.MULTILINE,
)


def _rewrite_imports(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        indent = match.group("indent")
        submodule = match.group("submodule")
        raw_names = match.group("names")
        alias = f"_libriichi_{submodule}"
        lines = [f"{indent}from libriichi import {submodule} as {alias}"]
        for item in raw_names.split(","):
            part = item.strip()
            if not part:
                continue
            if " as " in part:
                source, local = (p.strip() for p in part.split(" as ", 1))
            else:
                source = local = part
            if not source.isidentifier() or not local.isidentifier():
                raise RuntimeError(f"unsupported libriichi import item: {part!r}")
            lines.append(f"{indent}{local} = {alias}.{source}")
        return "\n".join(lines)

    return IMPORT_RE.sub(repl, text)


def apply(root: Path) -> None:
    mortal = root.expanduser().resolve() / "mortal"
    if not mortal.is_dir():
        raise RuntimeError(f"missing mortal dir: {mortal}")

    for path in sorted(mortal.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        updated = _rewrite_imports(text)
        if updated != text:
            if MARKER not in updated:
                updated = MARKER + "\n" + updated
            path.write_text(updated, encoding="utf-8")
            print(f"patched: {path}")
        py_compile.compile(str(path), doraise=True)

    engine = mortal / "engine.py"
    text = engine.read_text(encoding="utf-8")
    has_stage2_contract = (
        "game_mode = '4p'," in text
        and "action_space = None," in text
        and "self.game_mode = mode" in text
        and "self.action_space" in text
    )
    has_legacy_stage8_contract = (
        "game_mode = None," in text
        and "action_space = None," in text
        and "self.game_mode = game_mode" in text
        and "self.action_space = action_space" in text
    )
    if not (has_stage2_contract or has_legacy_stage8_contract):
        raise RuntimeError("MortalEngine unified runtime-mode contract missing")
    if MARKER not in text:
        text = MARKER + "\n" + text
        engine.write_text(text, encoding="utf-8")
    py_compile.compile(str(engine), doraise=True)

    for path in mortal.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if IMPORT_RE.search(text) or "from libriichi." in text:
            raise RuntimeError(f"legacy PyO3 submodule import remains: {path}")

    print("MORTAL_UNIFIED_PYTHON_ABI_STAGE8A_OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    apply(args.root)


if __name__ == "__main__":
    main()
