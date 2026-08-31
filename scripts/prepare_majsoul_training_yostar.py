from __future__ import annotations

import getpass
import hashlib
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import prepare_majsoul_training as base  # noqa: E402

YOSTAR_PATCHER = PROJECT_ROOT / "scripts" / "patch_tenhou_to_mjai_yostar.py"
YOSTAR_UID_ENV = "MORTAL_ROGS_MAJSOUL_YOSTAR_UID"
YOSTAR_TOKEN_ENV = "MORTAL_ROGS_MAJSOUL_YOSTAR_TOKEN"

_ORIGINAL_READ_CREDENTIALS = base.read_credentials


def _server_from_argv(argv: list[str] | None = None) -> str:
    args = list(sys.argv[1:] if argv is None else argv)
    for index, value in enumerate(args):
        if value == "--server" and index + 1 < len(args):
            return args[index + 1].lower()
        if value.startswith("--server="):
            return value.split("=", 1)[1].lower()
    return "cn"


def auth_mode_for_server(server: str) -> str:
    return "yostar-oauth-en-kr" if server.lower() == "en" else "native"


def install_tool(tools: Path) -> Path:
    if not YOSTAR_PATCHER.is_file():
        raise RuntimeError(f"managed Yostar patcher missing: {YOSTAR_PATCHER}")

    source = base.checkout(
        tools / "tenhou-to-mjai",
        base.MAJSOUL_TOOL_REPO,
        base.MAJSOUL_TOOL_SHA,
    )
    patcher_bytes = YOSTAR_PATCHER.read_bytes()
    patch_digest = hashlib.sha256(patcher_bytes).hexdigest()[:16]

    # The external checkout is a managed runtime cache. Always restore the exact pin
    # before applying our marker-checked auth compatibility edits so reruns are deterministic.
    commands = (
        ["git", "-C", str(source), "reset", "--hard", base.MAJSOUL_TOOL_SHA],
        [sys.executable, str(YOSTAR_PATCHER), "--root", str(source)],
        ["git", "-C", str(source), "diff", "--check"],
    )
    for cmd in commands:
        print("+", subprocess.list2cmdline(cmd), flush=True)
        subprocess.run(cmd, check=True)

    target = tools / "target"
    exe = target / "release" / ("tenhou-scraper.exe" if os.name == "nt" else "tenhou-scraper")
    marker = tools / f".built-{base.MAJSOUL_TOOL_SHA}-yostar-{patch_digest}"
    if not exe.is_file() or not marker.is_file():
        env = os.environ.copy()
        env["CARGO_TARGET_DIR"] = str(target)
        print("+ cargo build --release --locked [pinned Majsoul tool + Yostar EN patch]", flush=True)
        subprocess.run(["cargo", "build", "--release", "--locked"], cwd=source, env=env, check=True)
        marker.write_text(
            f"{base.MAJSOUL_TOOL_SHA}\nyostar_patcher_sha256={hashlib.sha256(patcher_bytes).hexdigest()}\n",
            encoding="utf-8",
        )
    return exe


def read_credentials(username_arg: str | None) -> tuple[str, str]:
    server = _server_from_argv()
    if server != "en":
        return _ORIGINAL_READ_CREDENTIALS(username_arg)

    uid = (username_arg or os.environ.get(YOSTAR_UID_ENV, "")).strip()
    if not uid:
        if not sys.stdin.isatty():
            raise RuntimeError(f"set {YOSTAR_UID_ENV} for non-interactive EN/Yostar use")
        uid = input("Mahjong Soul Yostar UID: ").strip()

    token = os.environ.get(YOSTAR_TOKEN_ENV, "")
    if not token:
        if not sys.stdin.isatty():
            raise RuntimeError(f"set {YOSTAR_TOKEN_ENV} for non-interactive EN/Yostar use")
        token = getpass.getpass("Mahjong Soul Yostar redirect token: ")

    if not uid.isdigit():
        raise RuntimeError("Mahjong Soul Yostar UID must be numeric")
    if not token:
        raise RuntimeError("Mahjong Soul Yostar redirect token cannot be empty")
    return uid, token


def main() -> int:
    server = _server_from_argv()
    base.install_tool = install_tool
    base.read_credentials = read_credentials
    print(f"MAJSOUL_AUTH_MODE server={server} mode={auth_mode_for_server(server)}", flush=True)
    try:
        return base.main()
    finally:
        os.environ.pop(YOSTAR_TOKEN_ENV, None)
        os.environ.pop(YOSTAR_UID_ENV, None)


if __name__ == "__main__":
    raise SystemExit(main())
