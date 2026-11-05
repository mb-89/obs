import json
import os
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource


ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "test" / "fixtures" / "document.json"
CORE_ROOT = Path(os.environ.get("OBS_CORE_PATH", ROOT / ".se" / "modules" / "obs"))
SYNC_COMMAND = "uv run python ../se/scripts/se_modules.py sync"


def require_core(core_root: Path) -> Path:
    """Return the core checkout, or fail naming where it looked and how to fix it."""
    schema = core_root / "src" / "obs" / "document.schema.json"
    if not schema.is_file():
        pytest.fail(
            f"test/conftest.py: obs core module not found, no {schema}. "
            f"Remedy: run `{SYNC_COMMAND}` from the repository root (se checked out next to "
            "this repository), or set OBS_CORE_PATH to an obs checkout.",
            pytrace=False,
        )
    return core_root


@pytest.fixture(scope="session")
def core_root() -> Path:
    """The pinned core checkout; tests read its JSON contracts, never its Python code."""
    return require_core(CORE_ROOT)


@pytest.fixture(scope="session")
def document_validator(core_root: Path) -> Draft202012Validator:
    schemas = core_root / "src" / "obs"
    figure = json.loads((schemas / "figure.schema.json").read_text(encoding="utf-8"))
    registry = Registry().with_resource("figure.schema.json", Resource.from_contents(figure))
    schema = json.loads((schemas / "document.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema, registry=registry)


@pytest.fixture
def document() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))
