from __future__ import annotations

from pathlib import Path

import pytest

from app.mortal import MortalController
from app.settings import Settings, normalize_mode


def make_settings(tmp_path: Path) -> Settings:
    project = tmp_path / "control"
    sanma = tmp_path / "Mortal_Sanma"
    yonma = tmp_path / "Mortal_4P"
    project.mkdir()
    sanma.mkdir()
    yonma.mkdir()
    return Settings(
        project_root=project,
        mortal_3p_root=sanma,
        mortal_4p_root=yonma,
        host="127.0.0.1",
        port=8188,
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


def test_runtime_layouts_are_isolated(tmp_path: Path) -> None:
    s = make_settings(tmp_path)
    p3 = s.runtime("3p")
    p4 = s.runtime("4p")

    assert p3.players == 3
    assert p3.mortal_dir == s.mortal_3p_root / "Mortal" / "mortal"
    assert p3.config_file.name == "config.sanma.toml"
    assert p3.evaluate_script == "one_vs_two.py"

    assert p4.players == 4
    assert p4.mortal_dir == s.mortal_4p_root / "mortal"
    assert p4.config_file.name == "config.toml"
    assert p4.evaluate_script == "one_vs_three.py"

    assert p3.models_dir != p4.models_dir
    assert p3.data_dir != p4.data_dir
    assert p3.runs_dir != p4.runs_dir
    assert p3.python_executable != p4.python_executable


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
    # On POSIX the 3P runtime intentionally falls back to the active Python
    # interpreter when the project venv is absent. Never overwrite that binary.
    if not runtime.python_executable.exists():
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
