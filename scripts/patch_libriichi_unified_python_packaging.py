from __future__ import annotations

import argparse
from pathlib import Path


PYPROJECT = '''[build-system]
requires = ["maturin>=1.9,<2.0"]
build-backend = "maturin"

[project]
name = "libriichi"
version = "0.1.0"
requires-python = ">=3.10"

[tool.maturin]
bindings = "pyo3"
module-name = "libriichi"
'''

MARKER = 'module-name = "libriichi"'


def apply(root: Path) -> None:
    root = root.expanduser().resolve()
    crate = root / "libriichi"
    cargo = crate / "Cargo.toml"
    lib_rs = crate / "src" / "lib.rs"
    if not cargo.is_file() or not lib_rs.is_file():
        raise RuntimeError(f"expected canonical libriichi crate: {crate}")

    cargo_text = cargo.read_text(encoding="utf-8")
    lib_text = lib_rs.read_text(encoding="utf-8")
    if '[package]\nname = "libriichi"' not in cargo_text:
        raise RuntimeError("unexpected libriichi Cargo package name")
    if '[lib]\nname = "riichi"' not in cargo_text:
        raise RuntimeError("unexpected libriichi Rust crate name")
    if "fn libriichi(" not in lib_text:
        raise RuntimeError("PyO3 module function is not named libriichi")

    pyproject = crate / "pyproject.toml"
    if pyproject.exists() and pyproject.read_text(encoding="utf-8") == PYPROJECT:
        print(f"unchanged: {pyproject}")
    else:
        pyproject.write_text(PYPROJECT, encoding="utf-8", newline="\n")
        print(f"created: {pyproject}")

    written = pyproject.read_text(encoding="utf-8")
    if MARKER not in written or 'bindings = "pyo3"' not in written:
        raise RuntimeError("libriichi Python packaging postcondition failed")
    print("MORTAL_UNIFIED_PYTHON_PACKAGING_OK")


def main() -> None:
    ap = argparse.ArgumentParser(description="Define the Python extension name for unified libriichi.")
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    apply(args.root)


if __name__ == "__main__":
    main()
