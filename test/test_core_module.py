from pathlib import Path

import pytest

from conftest import SYNC_COMMAND, require_core


def test_missing_core_error_names_the_path_and_the_sync_command(tmp_path: Path) -> None:
    missing = tmp_path / "obs"
    with pytest.raises(pytest.fail.Exception) as failure:
        require_core(missing)
    message = str(failure.value)
    assert str(missing / "src" / "obs" / "document.schema.json") in message
    assert SYNC_COMMAND in message
    assert "OBS_CORE_PATH" in message
