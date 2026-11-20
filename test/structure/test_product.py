import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[2]
USER_FACING_DIRECTORIES = (ROOT / "data", ROOT / "spec")


def test_build_output_configuration_keeps_distributions_out_of_root() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["tool"]["hatch"]["build"]["directory"] == "data/data_output/dist"
    assert not (ROOT / "dist").exists()


def test_user_facing_directories_stay_within_entry_caps() -> None:
    violations = []
    for directory in USER_FACING_DIRECTORIES:
        children = list(directory.iterdir())
        folders = [child for child in children if child.is_dir() and not child.name.startswith(".")]
        files = [
            child
            for child in children
            if child.is_file() and not child.name.startswith(".")
        ]
        if len(folders) > 5 or len(files) > 5:
            violations.append((directory.relative_to(ROOT), len(folders), len(files)))

    assert violations == []
