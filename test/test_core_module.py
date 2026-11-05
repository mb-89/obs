from pathlib import Path

import pytest

from conftest import README, SYNC_SECTION, require_core


def test_missing_core_error_names_the_path_and_points_at_the_sync_section(tmp_path: Path) -> None:
    missing = tmp_path / "obs"
    with pytest.raises(pytest.fail.Exception) as failure:
        require_core(missing)
    message = str(failure.value)
    assert str(missing / "src" / "obs" / "document.schema.json") in message
    assert f'{README.name}, section "{SYNC_SECTION}"' in message
    assert "OBS_CORE_PATH" in message


def test_the_sync_section_the_error_points_at_exists() -> None:
    headings = [line[3:].strip() for line in README.read_text(encoding="utf-8").splitlines()
                if line.startswith("## ")]
    assert SYNC_SECTION in headings
