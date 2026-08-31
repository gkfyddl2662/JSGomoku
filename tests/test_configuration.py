from datetime import date, datetime, timezone
from pathlib import Path
import urllib.parse

import pytest

from app.configuration import ConfigError, build_training_ablation_config, merge_preset
from scripts.prepare_majsoul_training import (
    AMAE_API_ROOT,
    API_LIMIT,
    MAJSOUL_TOOL_REPO,
    MAJSOUL_TOOL_SHA,
    MIN_WINDOW_MS,
    MODE_SOURCES,
    ApiRateLimiter,
    build_parser,
    collect_uuids,
    fetch_window,
    room_plan,
    room_url,
    utc_day_bounds,
)
from scripts.prepare_tenhou_training import HOUOU_SHA, SANMA_SHA, YONMA_SHA, split_for


def test_merge_preset_deep_merge():
    current = {"control": {"device": "cpu", "online": False}, "env": {"gamma": 1}}
    preset = {"control": {"device": "cuda", "batch_size": 512}}
    merged = merge_preset(current, preset)
    assert merged["control"]["device"] == "cuda"
    assert merged["control"]["online"] is False
    assert merged["control"]["batch_size"] == 512
    assert merged["env"]["gamma"] == 1


def test_training_ablation_variants_are_isolated_and_non_mutating(tmp_path: Path):
    base = {
        "control": {
            "online": True,
            "state_file": "original.pth",
            "best_state_file": "original-best.pth",
            "tensorboard_dir": "original-runs",
        },
        "game": {"mode": "3p", "num_players": 3},
        "rogs": {"enabled": True},
        "global_reward": {"enabled": False, "score_delta_weight": 0.15},
        "test_play": {"log_dir": "original-test"},
        "dataset": {"globs": ["same-data/**/*.json.gz"]},
    }
    expected = {
        "mortal": (False, False),
        "rogs": (True, False),
        "rogs-global": (True, True),
    }

    configs = {}
    for variant, toggles in expected.items():
        cfg = build_training_ablation_config(
            base,
            mode="3p",
            variant=variant,
            seed=17,
            mode_root=tmp_path / "runtime" / "3p",
        )
        configs[variant] = cfg
        assert (cfg["rogs"]["enabled"], cfg["global_reward"]["enabled"]) == toggles
        assert cfg["control"]["online"] is False
        assert cfg["control"]["training_seed"] == 17
        assert cfg["dataset"]["globs"] == base["dataset"]["globs"]
        assert cfg["experiment"]["variant"] == variant
        assert cfg["experiment"]["seed"] == 17
        assert f"seed-17/{variant}" in cfg["control"]["state_file"].replace("\\", "/")
        assert f"seed-17/{variant}" in cfg["control"]["tensorboard_dir"].replace("\\", "/")

    assert len({cfg["control"]["state_file"] for cfg in configs.values()}) == 3
    assert base["control"]["online"] is True
    assert base["control"]["state_file"] == "original.pth"
    assert base["rogs"]["enabled"] is True
    assert base["global_reward"]["enabled"] is False


def test_training_ablation_rejects_mismatched_mode_and_unknown_variant(tmp_path: Path):
    base = {"game": {"mode": "4p"}}
    with pytest.raises(ConfigError, match="does not match"):
        build_training_ablation_config(
            base,
            mode="3p",
            variant="rogs",
            seed=1,
            mode_root=tmp_path,
        )
    with pytest.raises(ConfigError, match="Unknown training ablation variant"):
        build_training_ablation_config(
            {"game": {"mode": "3p"}},
            mode="3p",
            variant="mystery",
            seed=1,
            mode_root=tmp_path,
        )


def test_tenhou_train_val_split_is_deterministic_and_stable():
    samples = [f"2026-log-{i}.xml" for i in range(1000)]
    first = [split_for(name, 0.05) for name in samples]
    second = [split_for(name, 0.05) for name in samples]
    assert first == second
    assert {"train", "val"} <= set(first)
    assert 20 <= first.count("val") <= 80


def test_tenhou_preparation_pins_and_authorization_gate():
    assert HOUOU_SHA == "d4ca693771517b67172521f2bd76517500db4a6e"
    assert SANMA_SHA == "e0bd7bffe24227f97600c710cffa4490117b634a"
    assert YONMA_SHA == "c133f7dbf61046feaf1af72369d9a44056807657"

    root = Path(__file__).resolve().parents[1]
    launcher = (root / "RUN_TENHOU_FULL.bat").read_text(encoding="utf-8")
    assert "authorized" in launcher
    assert "--accept-tenhou-log-terms" in launcher
    assert "RUN_TENHOU_FULL.bat full" in launcher


def test_majsoul_source_contract_and_pin():
    assert MAJSOUL_TOOL_REPO == "https://github.com/NikkeTryHard/tenhou-to-mjai.git"
    assert MAJSOUL_TOOL_SHA == "69fb75a51c7efef3212be603227b2a58a9717237"
    assert AMAE_API_ROOT == "https://5-data.amae-koromo.com/api/v2"

    assert MODE_SOURCES["3p"]["api"] == "pl3"
    assert MODE_SOURCES["3p"]["players"] == 3
    assert room_plan("3p", "high") == (("throne", 26), ("jade", 24), ("gold", 22))
    assert room_plan("3p", "all")[-3:] == (
        ("throne-east", 25),
        ("jade-east", 23),
        ("gold-east", 21),
    )

    assert MODE_SOURCES["4p"]["api"] == "pl4"
    assert MODE_SOURCES["4p"]["players"] == 4
    assert room_plan("4p", "high") == (("throne", 16), ("jade", 12), ("gold", 9))
    assert room_plan("4p", "all")[-3:] == (
        ("throne-east", 15),
        ("jade-east", 11),
        ("gold-east", 8),
    )

    url3 = room_url("3p", 26, 1000, 2000)
    url4 = room_url("4p", 16, 1000, 2000)
    assert "/pl3/games/1000/2000" in url3 and "mode=26" in url3
    assert "/pl4/games/1000/2000" in url4 and "mode=16" in url4
    assert urllib.parse.parse_qs(urllib.parse.urlsplit(url3).query)["limit"] == ["500"]


def test_majsoul_api_rate_day_window_and_cap_subdivision(monkeypatch: pytest.MonkeyPatch):
    ApiRateLimiter(4.0)
    with pytest.raises(ValueError):
        ApiRateLimiter(4.01)
    start, end = utc_day_bounds(date(2026, 8, 31))
    assert end - start == 86_399_999

    calls = []

    def fake_fetch_json(url, _limiter):
        calls.append(url)
        parts = urllib.parse.urlsplit(url).path.rstrip("/").split("/")
        start_ms, end_ms = int(parts[-2]), int(parts[-1])
        if end_ms - start_ms > MIN_WINDOW_MS:
            return [{"uuid": f"cap-{i}"} for i in range(API_LIMIT)]
        return [{"uuid": f"{start_ms}-{end_ms}"}]

    monkeypatch.setattr("scripts.prepare_majsoul_training.fetch_json", fake_fetch_json)
    records = fetch_window("3p", 26, 0, MIN_WINDOW_MS * 2, ApiRateLimiter(4))
    assert len(calls) == 3
    assert len(records) == 2


def _majsoul_record(uuid: str, mode_id: int, players: int, day: date) -> dict:
    stamp = int(datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc).timestamp())
    return {
        "uuid": uuid,
        "modeId": mode_id,
        "startTime": stamp,
        "players": [{"accountId": i} for i in range(players)],
    }


def test_majsoul_discovery_prioritizes_high_room_and_resumes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    requested = []
    day = date(2026, 8, 1)

    def fake_fetch_window(mode, room_mode, start_ms, end_ms, _limiter):
        current = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).date()
        requested.append((room_mode, current))
        assert mode == "3p"
        if room_mode != 26:
            pytest.fail("lower room must not be queried when Throne fills the target")
        return [
            _majsoul_record("a", 26, 3, current),
            _majsoul_record("b", 26, 3, current),
        ]

    monkeypatch.setattr("scripts.prepare_majsoul_training.fetch_window", fake_fetch_window)
    first = collect_uuids("3p", 2, tmp_path, day, day, 4, "high")
    assert first["selected"] == 2
    assert first["rooms"] == {"throne": 2}
    assert requested == [(26, day)]

    requested.clear()
    second = collect_uuids("3p", 2, tmp_path, day, day, 4, "high")
    assert second["selected"] == 2
    assert requested == []


def test_majsoul_parser_scope_and_no_password_cli():
    parser = build_parser()
    args = parser.parse_args(
        [
            "--runtime-root",
            "C:/Mortal_Unified",
            "--modes",
            "both",
            "--limit-3p",
            "5000",
            "--limit-4p",
            "5000",
            "--start-date",
            "2026-01-01",
            "--end-date",
            "2026-08-30",
            "--rooms",
            "all",
            "--server",
            "jp",
            "--username",
            "local@example.invalid",
        ]
    )
    assert args.start_date == "2026-01-01"
    assert args.end_date == "2026-08-30"
    assert args.rooms == "all"
    assert args.server == "jp"
    assert args.username == "local@example.invalid"

    option_strings = {option for action in parser._actions for option in action.option_strings}
    assert "--password" not in option_strings
    with pytest.raises(SystemExit):
        parser.parse_args(["--runtime-root", "x", "--rooms", "invalid"])


def test_majsoul_launcher_keeps_credentials_out_of_files():
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "RUN_MAJSOUL_FULL.bat").read_text(encoding="utf-8")
    script = (root / "scripts" / "prepare_majsoul_training.py").read_text(encoding="utf-8")
    for token in (
        "prepare_majsoul_training.py",
        "--api-rps 4",
        "--download-delay-ms 300",
        "--authorized-local-use",
        "authorized",
    ):
        assert token in launcher
    assert "getpass.getpass" in script
    assert 'shown[shown.index("--password") + 1] = "<redacted>"' in script
    assert '"credentials_persisted": False' in script
    assert 'p.add_argument("--password"' not in script


def test_majsoul_yostar_oauth_hex_auto_detection(monkeypatch: pytest.MonkeyPatch):
    import os
    import sys

    from scripts.prepare_majsoul_training_yostar import (
        YOSTAR_OAUTH_TYPE_ENV,
        YOSTAR_PACKET_HEX_ENV,
        parse_yostar_oauth2auth_hex,
        read_credentials,
    )

    packet_hex = (
        "020a000a142e6c712e4c6f6262792e6f617574683241757468124e"
        "0816"
        "122830313233343536373839616263646566303132333435363738396162636465663031323334353637"
        "1a0b3132333435363738393031"
        "2213576562474c5f323032322d392e39392e393939"
    )
    uid = "12345678901"
    code = "0123456789abcdef0123456789abcdef01234567"

    assert parse_yostar_oauth2auth_hex(packet_hex) == (uid, code, 22, "WebGL_2022-9.99.999")
    assert parse_yostar_oauth2auth_hex(uid) is None
    assert parse_yostar_oauth2auth_hex(code) is None
    with pytest.raises(RuntimeError, match="not a \\.lq\\.Lobby\\.oauth2Auth packet"):
        parse_yostar_oauth2auth_hex("00" * 64)

    monkeypatch.setattr(sys, "argv", ["prepare_majsoul_training_yostar.py", "--server", "en"])
    monkeypatch.setenv(YOSTAR_PACKET_HEX_ENV, packet_hex)
    monkeypatch.delenv(YOSTAR_OAUTH_TYPE_ENV, raising=False)
    parsed_uid, parsed_token = read_credentials(None)
    assert parsed_uid == uid
    assert parsed_token == code
    assert os.environ[YOSTAR_OAUTH_TYPE_ENV] == "22"
