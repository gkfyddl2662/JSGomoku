from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


CONSTS_SHA = "55bcf68aaec6e181b8355850b43cb28cc03b9ff1"
MARKER = "MORTAL_ROGS_UNIFIED_LIBRIICHI_STAGE1"

UNIFIED_CONSTS = r'''use crate::py_helper::add_submodule;

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

pub const MAX_VERSION: u32 = 4;

// MORTAL_ROGS_UNIFIED_LIBRIICHI_STAGE1
pub const ACTION_SPACE_3P: usize = 44;
pub const ACTION_SPACE_4P: usize = 46;
pub const ACTION_SPACE: usize = ACTION_SPACE_4P; // legacy 4P API

pub const GRP_SIZE_3P: usize = 6;
pub const GRP_SIZE_4P: usize = 7;
pub const GRP_SIZE: usize = GRP_SIZE_4P; // legacy 4P API

fn normalize_mode(mode: &str) -> PyResult<&'static str> {
    match mode.to_ascii_lowercase().as_str() {
        "3" | "3p" | "sanma" => Ok("3p"),
        "4" | "4p" | "yonma" => Ok("4p"),
        _ => Err(PyValueError::new_err(format!("unsupported game mode: {mode}"))),
    }
}

#[pyfunction]
#[inline]
pub const fn obs_shape(version: u32) -> (usize, usize) {
    match version {
        1 => (938, 34),
        2 => (942, 34),
        3 => (934, 34),
        4 => (1012, 34),
        _ => unreachable!(),
    }
}

#[pyfunction]
#[inline]
pub const fn oracle_obs_shape(version: u32) -> (usize, usize) {
    match version {
        1 => (211, 34),
        2 | 3 | 4 => (217, 34),
        _ => unreachable!(),
    }
}

#[pyfunction]
pub fn num_players_for(mode: &str) -> PyResult<usize> {
    Ok(if normalize_mode(mode)? == "3p" { 3 } else { 4 })
}

#[pyfunction]
pub fn action_space_for(mode: &str) -> PyResult<usize> {
    Ok(if normalize_mode(mode)? == "3p" {
        ACTION_SPACE_3P
    } else {
        ACTION_SPACE_4P
    })
}

#[pyfunction]
pub fn grp_size_for(mode: &str) -> PyResult<usize> {
    Ok(if normalize_mode(mode)? == "3p" {
        GRP_SIZE_3P
    } else {
        GRP_SIZE_4P
    })
}

#[pyfunction]
pub fn obs_shape_for(mode: &str, version: u32) -> PyResult<(usize, usize)> {
    match normalize_mode(mode)? {
        "3p" => match version {
            1 => Ok((936, 34)),
            2 => Ok((940, 34)),
            3 => Ok((932, 34)),
            4 => Ok((1010, 34)),
            _ => Err(PyValueError::new_err(format!(
                "unsupported 3P Mortal version: {version}"
            ))),
        },
        "4p" => match version {
            1..=4 => Ok(obs_shape(version)),
            _ => Err(PyValueError::new_err(format!(
                "unsupported 4P Mortal version: {version}"
            ))),
        },
        _ => unreachable!(),
    }
}

#[pyfunction]
pub fn oracle_obs_shape_for(mode: &str, version: u32) -> PyResult<(usize, usize)> {
    match normalize_mode(mode)? {
        "3p" => match version {
            1 => Ok((211, 34)),
            2..=4 => Ok((217, 34)),
            _ => Err(PyValueError::new_err(format!(
                "unsupported 3P Mortal version: {version}"
            ))),
        },
        "4p" => match version {
            1..=4 => Ok(oracle_obs_shape(version)),
            _ => Err(PyValueError::new_err(format!(
                "unsupported 4P Mortal version: {version}"
            ))),
        },
        _ => unreachable!(),
    }
}

pub(crate) fn register_module(
    py: Python<'_>,
    prefix: &str,
    super_mod: &Bound<'_, PyModule>,
) -> PyResult<()> {
    let m = PyModule::new(py, "consts")?;
    m.add_function(wrap_pyfunction!(obs_shape, &m)?)?;
    m.add_function(wrap_pyfunction!(oracle_obs_shape, &m)?)?;
    m.add_function(wrap_pyfunction!(num_players_for, &m)?)?;
    m.add_function(wrap_pyfunction!(action_space_for, &m)?)?;
    m.add_function(wrap_pyfunction!(grp_size_for, &m)?)?;
    m.add_function(wrap_pyfunction!(obs_shape_for, &m)?)?;
    m.add_function(wrap_pyfunction!(oracle_obs_shape_for, &m)?)?;
    m.add("MAX_VERSION", MAX_VERSION)?;
    m.add("ACTION_SPACE", ACTION_SPACE)?;
    m.add("ACTION_SPACE_3P", ACTION_SPACE_3P)?;
    m.add("ACTION_SPACE_4P", ACTION_SPACE_4P)?;
    m.add("GRP_SIZE", GRP_SIZE)?;
    m.add("GRP_SIZE_3P", GRP_SIZE_3P)?;
    m.add("GRP_SIZE_4P", GRP_SIZE_4P)?;
    add_submodule(py, prefix, super_mod, &m)
}
'''


def git_blob_sha(path: Path) -> str:
    return subprocess.run(
        ["git", "hash-object", str(path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def apply(root: Path) -> None:
    path = root / "libriichi" / "src" / "consts.rs"
    if not path.is_file():
        raise RuntimeError(f"libriichi consts.rs not found: {path}")

    original = path.read_text(encoding="utf-8")
    if MARKER not in original:
        actual = git_blob_sha(path)
        if actual != CONSTS_SHA:
            raise RuntimeError(
                f"unexpected stock libriichi consts.rs: expected {CONSTS_SHA}, got {actual}"
            )

    if original == UNIFIED_CONSTS:
        print(f"unchanged: {path}")
    else:
        backup = path.with_suffix(".rs.unified-stage1.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(UNIFIED_CONSTS, encoding="utf-8")
        print(f"patched: {path}")

    post = path.read_text(encoding="utf-8")
    required = (
        MARKER,
        "ACTION_SPACE_3P: usize = 44",
        "ACTION_SPACE_4P: usize = 46",
        "obs_shape_for",
        "oracle_obs_shape_for",
        "num_players_for",
    )
    missing = [needle for needle in required if needle not in post]
    if missing:
        raise RuntimeError(f"unified libriichi Stage 1 postconditions failed: {missing}")
    print("MORTAL_UNIFIED_LIBRIICHI_STAGE1_OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    apply(args.root.expanduser().resolve())


if __name__ == "__main__":
    main()
