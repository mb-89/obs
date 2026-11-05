import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
CORE_ROOT = Path(os.environ.get("OBS_CORE_PATH", ROOT / ".se" / "modules" / "obs"))
if not CORE_ROOT.is_dir():
    raise RuntimeError("Synchronize the obs module or set OBS_CORE_PATH to its checkout.")
sys.path.insert(0, str(CORE_ROOT / "src"))

from obs.capabilities import build_capability_reference
from obs.document import call_adapter


def test_smoke_adapter_reads_a_core_document(tmp_path: Path) -> None:
    reference = build_capability_reference(
        CORE_ROOT / "spec" / "capabilities",
        CORE_ROOT / "spec" / "capabilities" / "coverage.json",
    )
    reference_path = tmp_path / "capabilities.json"
    reference_path.write_text(json.dumps(reference), encoding="utf-8")
    destination = tmp_path / "document.html"

    call_adapter(
        "html",
        ROOT / "adapters.json",
        ROOT / "test" / "fixtures" / "document.json",
        destination,
        reference_path,
    )

    assert destination.read_text(encoding="utf-8") == (
        "<!doctype html>\n"
        "<html lang=\"en\"><head><meta charset=\"utf-8\"><title>Fixture document</title></head>"
        "<body><h1>Fixture document</h1></body></html>\n"
    )
