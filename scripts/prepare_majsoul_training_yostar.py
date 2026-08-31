from __future__ import annotations

import getpass
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import prepare_majsoul_training as base  # noqa: E402

YOSTAR_PATCHER = PROJECT_ROOT / "scripts" / "patch_tenhou_to_mjai_yostar.py"
YOSTAR_UID_ENV = "MORTAL_ROGS_MAJSOUL_YOSTAR_UID"
YOSTAR_TOKEN_ENV = "MORTAL_ROGS_MAJSOUL_YOSTAR_TOKEN"
YOSTAR_PACKET_HEX_ENV = "MORTAL_ROGS_MAJSOUL_YOSTAR_OAUTH_HEX"
YOSTAR_OAUTH_TYPE_ENV = "MORTAL_ROGS_MAJSOUL_YOSTAR_OAUTH_TYPE"
YOSTAR_LOCALE_ENV = "MORTAL_ROGS_MAJSOUL_YOSTAR_LOCALE"
YOSTAR_OAUTH_METHOD = b".lq.Lobby.oauth2Auth"
AMAE_SAFE_RPS = 1.0
AMAE_MAX_ATTEMPTS = 8
AMAE_MAX_BACKOFF_SECONDS = 60.0

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


def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    value = 0
    shift = 0
    for _ in range(10):
        if pos >= len(data):
            raise RuntimeError("truncated protobuf varint in Yostar oauth2Auth packet")
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, pos
        shift += 7
    raise RuntimeError("invalid protobuf varint in Yostar oauth2Auth packet")


def _parse_protobuf_fields(data: bytes) -> dict[int, list[int | bytes]]:
    fields: dict[int, list[int | bytes]] = {}
    pos = 0
    while pos < len(data):
        key, pos = _read_varint(data, pos)
        field = key >> 3
        wire = key & 0x07
        if field <= 0:
            raise RuntimeError("invalid protobuf field in Yostar oauth2Auth packet")
        if wire == 0:
            value, pos = _read_varint(data, pos)
        elif wire == 1:
            end = pos + 8
            if end > len(data):
                raise RuntimeError("truncated fixed64 field in Yostar oauth2Auth packet")
            value = data[pos:end]
            pos = end
        elif wire == 2:
            length, pos = _read_varint(data, pos)
            end = pos + length
            if end > len(data):
                raise RuntimeError("truncated length-delimited field in Yostar oauth2Auth packet")
            value = data[pos:end]
            pos = end
        elif wire == 5:
            end = pos + 4
            if end > len(data):
                raise RuntimeError("truncated fixed32 field in Yostar oauth2Auth packet")
            value = data[pos:end]
            pos = end
        else:
            raise RuntimeError(f"unsupported protobuf wire type {wire} in Yostar oauth2Auth packet")
        fields.setdefault(field, []).append(value)
    return fields


def parse_yostar_oauth2auth_hex(value: str) -> tuple[str, str, int, str] | None:
    """Parse a captured oauth2Auth websocket/protobuf packet.

    Returns (uid, redirect_code, oauth_type, client_version). Short ordinary
    UID/token strings intentionally return None so normal credential entry keeps
    working. A long hex packet that is not oauth2Auth fails explicitly.
    """
    raw = value.strip()
    if not raw:
        return None

    compact = re.sub(r"(?i)0x", "", raw)
    compact = re.sub(r"[\s:_-]+", "", compact)
    if len(compact) < 48 or not re.fullmatch(r"[0-9a-fA-F]+", compact):
        return None
    if len(compact) % 2:
        raise RuntimeError("Yostar oauth2Auth hex packet has an odd number of hex digits")

    try:
        packet = bytes.fromhex(compact)
    except ValueError as exc:
        raise RuntimeError("invalid Yostar oauth2Auth hex packet") from exc

    marker_pos = packet.find(YOSTAR_OAUTH_METHOD)
    if marker_pos < 0:
        raise RuntimeError("hex input is not a .lq.Lobby.oauth2Auth packet")

    pos = marker_pos + len(YOSTAR_OAUTH_METHOD)
    key, pos = _read_varint(packet, pos)
    if (key >> 3, key & 0x07) != (2, 2):
        raise RuntimeError("oauth2Auth packet wrapper is missing protobuf payload field 2")
    payload_len, pos = _read_varint(packet, pos)
    end = pos + payload_len
    if end > len(packet):
        raise RuntimeError("oauth2Auth packet protobuf payload is truncated")

    fields = _parse_protobuf_fields(packet[pos:end])
    try:
        oauth_type_raw = fields[1][0]
        code_raw = fields[2][0]
        uid_raw = fields[3][0]
        version_raw = fields[4][0]
    except (KeyError, IndexError) as exc:
        raise RuntimeError("oauth2Auth packet is missing type/code/uid/version fields") from exc

    if not isinstance(oauth_type_raw, int):
        raise RuntimeError("oauth2Auth type field is not a varint")
    if not all(isinstance(item, bytes) for item in (code_raw, uid_raw, version_raw)):
        raise RuntimeError("oauth2Auth code/uid/version fields are not strings")

    try:
        code = code_raw.decode("utf-8").strip()
        uid = uid_raw.decode("utf-8").strip()
        client_version = version_raw.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise RuntimeError("oauth2Auth packet contains non-UTF-8 credential fields") from exc

    if not uid.isdigit():
        raise RuntimeError("oauth2Auth packet UID is not numeric")
    if not code:
        raise RuntimeError("oauth2Auth packet redirect code is empty")
    if not client_version.startswith("WebGL_"):
        raise RuntimeError("oauth2Auth packet client version is not a WebGL version")
    if not (0 < oauth_type_raw < 256):
        raise RuntimeError(f"oauth2Auth packet OAuth type is out of range: {oauth_type_raw}")
    return uid, code, oauth_type_raw, client_version


def _use_packet_credentials(packet_hex: str) -> tuple[str, str] | None:
    parsed = parse_yostar_oauth2auth_hex(packet_hex)
    if parsed is None:
        return None
    uid, token, oauth_type, client_version = parsed
    os.environ[YOSTAR_OAUTH_TYPE_ENV] = str(oauth_type)
    print(
        f"MAJSOUL_YOSTAR_PACKET_PARSED oauth_type={oauth_type} client_version={client_version}",
        flush=True,
    )
    return uid, token


class AmaeSafeRateLimiter:
    """Conservative limiter for public Amae metadata discovery.

    The base CLI still accepts up to 4 RPS for backwards compatibility, but the
    Yostar preparation path clamps the effective rate to 1 RPS to avoid bursts.
    """

    def __init__(self, rps: float) -> None:
        if not 0 < rps <= 4:
            raise ValueError("Amae-Koromo RPS must be in (0, 4]")
        self.requested_rps = rps
        self.effective_rps = min(rps, AMAE_SAFE_RPS)
        self.interval = 1.0 / self.effective_rps
        self.last_started: float | None = None

    def wait(self) -> None:
        if self.last_started is not None:
            remaining = self.interval - (time.monotonic() - self.last_started)
            if remaining > 0:
                time.sleep(remaining)
        self.last_started = time.monotonic()


def _retry_after_seconds(exc: urllib.error.HTTPError, attempt: int) -> float:
    retry_after = exc.headers.get("Retry-After") if exc.headers is not None else None
    if retry_after:
        try:
            return min(AMAE_MAX_BACKOFF_SECONDS, max(1.0, float(retry_after)))
        except ValueError:
            pass
    return min(AMAE_MAX_BACKOFF_SECONDS, 2.0 * (2**attempt))


def fetch_json_resilient(url: str, limiter: AmaeSafeRateLimiter) -> object:
    """Fetch Amae JSON without treating ordinary 429s as fatal immediately."""
    for attempt in range(AMAE_MAX_ATTEMPTS):
        limiter.wait()
        req = urllib.request.Request(
            url,
            headers={"User-Agent": base.USER_AGENT, "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read(1024).decode("utf-8", errors="replace")
            except Exception:
                detail = ""

            if exc.code == 429:
                if "x-cap-token-required" in detail.lower():
                    raise RuntimeError(
                        "Amae-Koromo requires a browser CAP proof for this request; "
                        "automatic metadata discovery cannot bypass that challenge."
                    ) from exc
                if attempt == AMAE_MAX_ATTEMPTS - 1:
                    raise RuntimeError(
                        f"Amae-Koromo kept returning HTTP 429 after {AMAE_MAX_ATTEMPTS} attempts; "
                        "the local discovery journal is resumable."
                    ) from exc
                wait_s = _retry_after_seconds(exc, attempt)
                print(
                    f"MAJSOUL_AMAE_RATE_LIMIT status=429 attempt={attempt + 1}/{AMAE_MAX_ATTEMPTS} "
                    f"wait_s={wait_s:g}",
                    flush=True,
                )
                time.sleep(wait_s)
                continue

            if exc.code >= 500:
                if attempt == AMAE_MAX_ATTEMPTS - 1:
                    raise
                wait_s = min(AMAE_MAX_BACKOFF_SECONDS, 1.0 * (2**attempt))
                print(
                    f"MAJSOUL_AMAE_RETRY status={exc.code} attempt={attempt + 1}/{AMAE_MAX_ATTEMPTS} "
                    f"wait_s={wait_s:g}",
                    flush=True,
                )
                time.sleep(wait_s)
                continue
            raise
        except (TimeoutError, urllib.error.URLError):
            if attempt == AMAE_MAX_ATTEMPTS - 1:
                raise
            wait_s = min(AMAE_MAX_BACKOFF_SECONDS, 1.0 * (2**attempt))
            print(
                f"MAJSOUL_AMAE_RETRY status=network attempt={attempt + 1}/{AMAE_MAX_ATTEMPTS} "
                f"wait_s={wait_s:g}",
                flush=True,
            )
            time.sleep(wait_s)
    raise RuntimeError("unreachable")


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

    packet_env = os.environ.get(YOSTAR_PACKET_HEX_ENV, "").strip()
    if packet_env:
        packet_credentials = _use_packet_credentials(packet_env)
        if packet_credentials is None:
            raise RuntimeError(f"{YOSTAR_PACKET_HEX_ENV} does not contain an oauth2Auth hex packet")
        return packet_credentials

    uid_or_packet = (username_arg or os.environ.get(YOSTAR_UID_ENV, "")).strip()
    if not uid_or_packet:
        if not sys.stdin.isatty():
            raise RuntimeError(
                f"set {YOSTAR_PACKET_HEX_ENV} or {YOSTAR_UID_ENV} for non-interactive EN/Yostar use"
            )
        uid_or_packet = input("Mahjong Soul Yostar UID or oauth2Auth packet hex: ").strip()

    packet_credentials = _use_packet_credentials(uid_or_packet)
    if packet_credentials is not None:
        return packet_credentials

    uid = uid_or_packet
    token = os.environ.get(YOSTAR_TOKEN_ENV, "")
    if not token:
        if not sys.stdin.isatty():
            raise RuntimeError(f"set {YOSTAR_TOKEN_ENV} for non-interactive EN/Yostar use")
        token = getpass.getpass("Mahjong Soul Yostar redirect token: ")

    if not uid.isdigit():
        raise RuntimeError("Mahjong Soul Yostar UID must be numeric, or paste the full oauth2Auth hex packet")
    if not token:
        raise RuntimeError("Mahjong Soul Yostar redirect token cannot be empty")
    return uid, token


def main() -> int:
    server = _server_from_argv()
    base.install_tool = install_tool
    base.read_credentials = read_credentials
    if server == "en":
        base.ApiRateLimiter = AmaeSafeRateLimiter
        base.fetch_json = fetch_json_resilient
        print(
            f"MAJSOUL_AMAE_POLICY requested_rps<=4 effective_rps<={AMAE_SAFE_RPS:g} "
            f"retry_attempts={AMAE_MAX_ATTEMPTS}",
            flush=True,
        )
    print(f"MAJSOUL_AUTH_MODE server={server} mode={auth_mode_for_server(server)}", flush=True)
    try:
        return base.main()
    finally:
        for name in (
            YOSTAR_TOKEN_ENV,
            YOSTAR_UID_ENV,
            YOSTAR_PACKET_HEX_ENV,
            YOSTAR_OAUTH_TYPE_ENV,
            YOSTAR_LOCALE_ENV,
        ):
            os.environ.pop(name, None)


if __name__ == "__main__":
    raise SystemExit(main())
