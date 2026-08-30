from __future__ import annotations

from pathlib import Path

from app.mortal import MortalController
from app.settings import Settings


def touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def make_unified_settings(tmp_path: Path) -> Settings:
    project = tmp_path / "mortal-rogs"
    unified = tmp_path / "Mortal_Unified"
    project.mkdir()
    unified.mkdir()
    return Settings(
        project_root=project,
        mortal_3p_root=tmp_path / "legacy-3p",
        mortal_4p_root=tmp_path / "legacy-4p",
        host="127.0.0.1",
        port=8188,
        runtime_root=tmp_path / "legacy-runtime",
        mortal_unified_root=unified,
    )


def test_unified_modes_share_code_python_and_libriichi_root(tmp_path: Path) -> None:
    s = make_unified_settings(tmp_path)
    p3 = s.runtime("3p")
    p4 = s.runtime("4p")

    assert p3.unified and p4.unified
    assert p3.root == p4.root == s.mortal_unified_root
    assert p3.mortal_dir == p4.mortal_dir == s.mortal_unified_root / "mortal"
    assert p3.python_executable == p4.python_executable
    assert p3.python_executable.parent.parent == s.mortal_unified_root / ".venv"

    assert p3.config_file.name == "config.3p.toml"
    assert p4.config_file.name == "config.4p.toml"
    assert p3.mode_root == s.mortal_unified_root / "runtime" / "3p"
    assert p4.mode_root == s.mortal_unified_root / "runtime" / "4p"
    assert p3.models_dir != p4.models_dir
    assert p3.data_dir != p4.data_dir
    assert p3.runs_dir != p4.runs_dir
    assert p3.evaluate_script == "one_vs_two.py"
    assert p4.evaluate_script == "one_vs_three.py"


def test_unified_controller_routes_both_modes_through_one_python(tmp_path: Path) -> None:
    s = make_unified_settings(tmp_path)
    controller = MortalController(s)
    p3 = s.runtime("3p")
    p4 = s.runtime("4p")

    touch(p3.python_executable)
    for runtime in (p3, p4):
        touch(runtime.config_file)
    touch(p3.mortal_dir / "one_vs_two.py")
    touch(p4.mortal_dir / "one_vs_three.py")

    cmd3, cwd3, env3 = controller.command_for("evaluate", {"mode": "3p"})
    cmd4, cwd4, env4 = controller.command_for("evaluate", {"mode": "4p"})

    assert Path(cmd3[0]) == Path(cmd4[0]) == p3.python_executable
    assert cwd3 == cwd4 == p3.mortal_dir
    assert cmd3[1] == "one_vs_two.py"
    assert cmd4[1] == "one_vs_three.py"
    assert env3["MORTAL_CFG"].endswith("config.3p.toml")
    assert env4["MORTAL_CFG"].endswith("config.4p.toml")
    assert env3["MORTAL_GAME_MODE"] == "3p"
    assert env4["MORTAL_GAME_MODE"] == "4p"
    assert env3["MORTAL_UNIFIED_ROOT"] == str(p3.root)
    assert env4["MORTAL_UNIFIED_ROOT"] == str(p4.root)


def test_unified_patch_command_uses_complete_aggregator(tmp_path: Path) -> None:
    s = make_unified_settings(tmp_path)
    controller = MortalController(s)
    cmd, cwd, env = controller.command_for("patch", {"mode": "3p"})

    assert Path(cmd[1]).name == "patch_mortal_unified_all.py"
    assert cmd[-2:] == ["--root", str(s.mortal_unified_root)]
    assert cwd == s.project_root
    assert env["MORTAL_UNIFIED_ROOT"] == str(s.mortal_unified_root)


def test_unified_status_exposes_shared_root_and_mode_root(tmp_path: Path) -> None:
    s = make_unified_settings(tmp_path)
    controller = MortalController(s)
    status3 = controller.status("3p")
    status4 = controller.status("4p")

    assert status3["unified"] is True
    assert status4["unified"] is True
    assert status3["mortal_root"] == status4["mortal_root"]
    assert status3["mode_root"].endswith(str(Path("runtime") / "3p"))
    assert status4["mode_root"].endswith(str(Path("runtime") / "4p"))


def test_unified_bootstrap_routes_one_click_rust_install_flag(tmp_path: Path, monkeypatch) -> None:
    s = make_unified_settings(tmp_path)
    controller = MortalController(s)
    monkeypatch.setattr("app.mortal.os.name", "nt")

    cmd, cwd, env = controller.command_for(
        "bootstrap_runtime",
        {"mode": "3p", "install_rust_if_missing": True},
    )

    assert Path(cmd[5]).name == "bootstrap_unified_runtime.ps1"
    assert "-InstallRoot" in cmd
    assert str(s.mortal_unified_root) in cmd
    assert "-InstallRustIfMissing" in cmd
    assert "-Mode" not in cmd
    assert cwd == s.project_root
    assert env == {}
