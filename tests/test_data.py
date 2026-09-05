from decidr.config import PROJ_ROOT


def test_project_root_contains_pyproject():
    assert (PROJ_ROOT / "pyproject.toml").is_file()
