import os
import sys

import pytest

from scripts.prepare_majsoul_training_yostar import (
    YOSTAR_OAUTH_TYPE_ENV,
    YOSTAR_PACKET_HEX_ENV,
    parse_yostar_oauth2auth_hex,
    read_credentials,
)

# Synthetic capture-shaped packet. These are deliberately non-account test values.
SYNTHETIC_OAUTH2AUTH_HEX = (
    "020a000a142e6c712e4c6f6262792e6f617574683241757468124e"
    "0816"
    "122830313233343536373839616263646566303132333435363738396162636465663031323334353637"
    "1a0b3132333435363738393031"
    "2213576562474c5f323032322d392e39392e393939"
)
SYNTHETIC_UID = "12345678901"
SYNTHETIC_CODE = "0123456789abcdef0123456789abcdef01234567"


def test_yostar_oauth2auth_full_hex_auto_detection():
    parsed = parse_yostar_oauth2auth_hex(SYNTHETIC_OAUTH2AUTH_HEX)
    assert parsed == (SYNTHETIC_UID, SYNTHETIC_CODE, 22, "WebGL_2022-9.99.999")

    # Common packet-dump formatting is accepted too.
    spaced = " ".join(
        SYNTHETIC_OAUTH2AUTH_HEX[index : index + 2]
        for index in range(0, len(SYNTHETIC_OAUTH2AUTH_HEX), 2)
    )
    assert parse_yostar_oauth2auth_hex(spaced) == parsed

    # Ordinary UID/redirect-code values are not mistaken for captured packets.
    assert parse_yostar_oauth2auth_hex(SYNTHETIC_UID) is None
    assert parse_yostar_oauth2auth_hex(SYNTHETIC_CODE) is None


def test_yostar_oauth2auth_hex_rejects_wrong_packet():
    with pytest.raises(RuntimeError, match="not a \\.lq\\.Lobby\\.oauth2Auth packet"):
        parse_yostar_oauth2auth_hex("00" * 64)


def test_yostar_packet_env_sets_captured_oauth_type(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sys, "argv", ["prepare_majsoul_training_yostar.py", "--server", "en"])
    monkeypatch.setenv(YOSTAR_PACKET_HEX_ENV, SYNTHETIC_OAUTH2AUTH_HEX)
    monkeypatch.delenv(YOSTAR_OAUTH_TYPE_ENV, raising=False)

    uid, token = read_credentials(None)
    assert uid == SYNTHETIC_UID
    assert token == SYNTHETIC_CODE
    assert os.environ[YOSTAR_OAUTH_TYPE_ENV] == "22"
