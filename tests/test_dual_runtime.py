from __future__ import annotations

from pathlib import Path

import pytest

from app.mortal import MortalController
from app.settings import Settings, normalize_mode


def make_settings(tmp_path: Path) -> Settings:
    project = tmp_path / "control"
    runtime_root = tmp_path / "Mortal_ROGS_Runtime"
    sanma = runtime_root / "3p"
    yonma = runtime_root / "4p"
    project.mkdir()
    sanma.mkdir(parents=True)
    yonma.mkdir(parents=True)
    return Settings(
        project_root=project,
        mortal_3p_root=sanma,
        mortal_4p_root=yonma,
        host="127.0.0.1",
        port=8188,
        runtime_root=runtime_root,
    )


def make_unified_settings(tmp_path: Path) -> Settings:
    project = tmp_path / "control"
    legacy = tmp_path / "legacy"
    unified = tmp_path / "Mortal_Unified"
    project.mkdir()
    legacy.mkdir()
    unified.mkdir()
    return Settings(
        project_root=project,
        mortal_3p_root=legacy / "3p",
        mortal_4p_root=legacy / "4p",
        host="127.0.0.1",
        port=8188,
        runtime_root=legacy,
        mortal_unified_root=unified,
    )


def touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def test_mode_aliases_and_rejection() -> None:
    assert normalize_mode("sanma") == "3p"
    assert normalize_mode("3") == "3p"
    assert normalize_mode("yonma") == "4p"
    assert normalize_mode("4") == "4p"
    with pytest.raises(ValueError):
        normalize_mode("5p")


def test_runtime_layouts_share_one_root_but_keep_abis_isolated(tmp_path: Path) -> None:
    s = make_settings(tmp_path)
    p3 = s.runtime("3p")
    p4 = s.runtime("4p")

    assert p3.players == 3
    assert p3.root.parent == s.runtime_root
    assert p3.root.name == "3p"
    assert p3.mortal_dir == s.mortal_3p_root / "Mortal" / "mortal"
    assert p3.config_file.name == "config.sanma.toml"
    assert p3.evaluate_script == "one_vs_two.py"

    assert p4.players == 4
    assert p4.root.parent == s.runtime_root
    assert p4.root.name == "4p"
    assert p4.mortal_dir == s.mortal_4p_root / "mortal"
    assert p4.config_file.name == "config.toml"
    assert p4.evaluate_script == "one_vs_three.py"

    assert p3.models_dir != p4.models_dir
    assert p3.data_dir != p4.data_dir
    assert p3.runs_dir != p4.runs_dir
    assert p3.python_executable != p4.python_executable
    assert p3.python_executable.parent.parent == p3.root / ".venv"
    assert p4.python_executable.parent.parent == p4.root / ".venv"


def test_controller_routes_4p_evaluation_to_stock_mortal(tmp_path: Path) -> None:
    s = make_settings(tmp_path)
    runtime = s.runtime("4p")
    touch(runtime.python_executable)
    touch(runtime.config_file)
    touch(runtime.mortal_dir / "one_vs_three.py")

    controller = MortalController(s)
    cmd, cwd, env = controller.command_for("evaluate", {"mode": "4p"})

    assert Path(cmd[0]) == runtime.python_executable
    assert cmd[1] == "one_vs_three.py"
    assert cwd == runtime.mortal_dir
    assert env["MORTAL_GAME_MODE"] == "4p"
    assert env["MORTAL_PLAYER_COUNT"] == "4"
    assert env["MORTAL_CFG"] == str(runtime.config_file)


def test_controller_routes_3p_evaluation_to_sanma_mortal(tmp_path: Path) -> None:
    s = make_settings(tmp_path)
    runtime = s.runtime("3p")
    touch(runtime.python_executable)
    touch(runtime.config_file)
    touch(runtime.mortal_dir / "one_vs_two.py")

    controller = MortalController(s)
    cmd, cwd, env = controller.command_for("evaluate", {"mode": "3p"})

    assert Path(cmd[0]) == runtime.python_executable
    assert cmd[1] == "one_vs_two.py"
    assert cwd == runtime.mortal_dir
    assert env["MORTAL_GAME_MODE"] == "3p"
    assert env["MORTAL_PLAYER_COUNT"] == "3"
    assert env["MORTAL_CFG"] == str(runtime.config_file)


def test_controller_routes_unified_training_ablation(tmp_path: Path) -> None:
    s = make_unified_settings(tmp_path)
    runtime = s.runtime("3p")
    touch(runtime.python_executable)
    touch(runtime.config_file)
    touch(runtime.mortal_dir / "train.py")
    runner = s.project_root / "scripts" / "run_training_ablation.py"
    touch(runner)

    controller = MortalController(s)
    cmd, cwd, env = controller.command_for(
        "train_ablation",
        {"mode": "3p", "variant": "rogs-global", "seed": 17, "fresh": True},
    )

    assert Path(cmd[0]) == runtime.python_executable
    assert Path(cmd[1]) == runner
    assert cmd[cmd.index("--runtime-root") + 1] == str(runtime.root)
    assert cmd[cmd.index("--mode") + 1] == "3p"
    assert cmd[cmd.index("--variant") + 1] == "rogs-global"
    assert cmd[cmd.index("--seed") + 1] == "17"
    assert "--fresh" in cmd
    assert cwd == s.project_root
    assert env["MORTAL_GAME_MODE"] == "3p"


def test_controller_routes_unified_bidirectional_model_comparison(tmp_path: Path) -> None:
    s = make_unified_settings(tmp_path)
    runtime = s.runtime("4p")
    touch(runtime.python_executable)
    touch(runtime.config_file)
    touch(runtime.mortal_dir / "one_vs_three.py")
    runner = s.project_root / "scripts" / "run_model_comparison.py"
    touch(runner)
    touch(runtime.models_dir / "candidate.pth")
    touch(runtime.models_dir / "baseline.pth")

    controller = MortalController(s)
    cmd, cwd, env = controller.command_for(
        "model_compare",
        {
            "mode": "4p",
            "candidate": "candidate.pth",
            "baseline": "baseline.pth",
            "seed_start": 23000,
            "seed_count": 12,
            "seed_key": "0x1234",
            "profile": "mahjongsoul",
            "device": "cuda:0",
            "enable_compile": True,
            "enable_amp": False,
            "fresh": True,
        },
    )

    assert Path(cmd[0]) == runtime.python_executable
    assert Path(cmd[1]) == runner
    assert cmd[cmd.index("--mode") + 1] == "4p"
    assert cmd[cmd.index("--candidate") + 1] == "candidate.pth"
    assert cmd[cmd.index("--baseline") + 1] == "baseline.pth"
    assert cmd[cmd.index("--seed-start") + 1] == "23000"
    assert cmd[cmd.index("--seed-count") + 1] == "12"
    assert cmd[cmd.index("--seed-key") + 1] == "0x1234"
    assert cmd[cmd.index("--profile") + 1] == "mahjongsoul"
    assert cmd[cmd.index("--device") + 1] == "cuda:0"
    assert "--compile" in cmd
    assert "--no-amp" in cmd
    assert "--fresh" in cmd
    assert cwd == s.project_root
    assert env["MORTAL_GAME_MODE"] == "4p"


def test_controller_rejects_model_comparison_path_escape(tmp_path: Path) -> None:
    s = make_unified_settings(tmp_path)
    runtime = s.runtime("3p")
    touch(runtime.python_executable)
    touch(runtime.config_file)
    touch(runtime.mortal_dir / "one_vs_two.py")
    touch(s.project_root / "scripts" / "run_model_comparison.py")
    touch(runtime.models_dir / "baseline.pth")
    outside = runtime.models_dir.parent / "outside.pth"
    touch(outside)

    controller = MortalController(s)
    with pytest.raises(ValueError, match="escapes"):
        controller.command_for(
            "model_compare",
            {
                "mode": "3p",
                "candidate": "../outside.pth",
                "baseline": "baseline.pth",
            },
        )
