import json
import re
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_document_adapter_contract_points_to_note_records() -> None:
    architecture = (ROOT / "spec" / "design_input" / "architecture.md").read_text(encoding="utf-8")
    contract = architecture.split("## Document-adapter contract", 1)[1].split("\n## ", 1)[0]

    assert "[[capabilities/bases#Note records|" in contract


def test_architecture_links_the_document_to_the_glossary() -> None:
    architecture = (ROOT / "spec" / "design_input" / "architecture.md").read_text(encoding="utf-8")
    assert "[[quality#Glossary|" in architecture


def test_document_adapter_contract_records_why_assets_carry_their_bytes() -> None:
    architecture = (ROOT / "spec" / "design_input" / "architecture.md").read_text(encoding="utf-8")
    contract = architecture.split("## Document-adapter contract", 1)[1].split("\n## ", 1)[0]
    decision = contract.split("### Asset bytes", 1)[1]

    assert "base64 `data`" in decision
    assert "asset root" in decision
    assert "[[product#Goals]]" in decision


def test_asset_bytes_records_that_a_fetched_remote_image_carries_data_without_a_path() -> None:
    architecture = (ROOT / "spec" / "design_input" / "architecture.md").read_text(encoding="utf-8")
    decision = " ".join(architecture.split("### Asset bytes", 1)[1].split("\n## ", 1)[0].split())

    assert "carries neither `path` nor `data`" not in decision
    assert "A remote image carries the `data` the build fetched" in decision


def test_the_adapter_call_states_how_an_adapter_writes_warnings() -> None:
    """An adapter's warnings: stderr, one per line, in the error form, which the core shows (cli.md)."""
    architecture = (ROOT / "spec" / "design_input" / "architecture.md").read_text(encoding="utf-8")
    call = " ".join(architecture.split("### Adapter call", 1)[1].split("\n### ", 1)[0].split())

    assert "writes each warning to stderr, one per line" in call
    assert "[[input-model#Chapter content|" in call
    assert "[[cli#One-call build]]" in call


MEASURE = "measure"


def misplaced_measurement_scripts(root: Path) -> list[str]:
    """Each runnable script of a part's tests that no other test file names, outside its test/measure/.

    A part is the core and each adapter adapters.json registers (architecture.md, Repository layout).
    """
    registry = json.loads((root / "adapters.json").read_text(encoding="utf-8"))["adapters"]
    parts = [root, *(root / Path(manifest).parent for manifest in registry.values())]
    found = []
    for part in parts:
        tests = part / "test"
        sources = {path: path.read_text(encoding="utf-8") for path in tests.rglob("*.py")
                   if "node_modules" not in path.parts}
        for path, source in sorted(sources.items()):
            if path.parent == tests / MEASURE or not re.search(r'^if __name__ == "__main__":', source, re.M):
                continue
            named = re.compile(rf"\b{re.escape(path.stem)}\b")
            if not any(named.search(other) for other_path, other in sources.items() if other_path != path):
                found.append(f"{path.relative_to(root).as_posix()}: a runnable script no test names "
                             f"belongs in {(tests / MEASURE).relative_to(root).as_posix()}/ "
                             "(spec/design_input/architecture.md#repository-layout)")
    return found


def test_measurement_scripts_live_in_their_parts_measure_folder() -> None:
    assert misplaced_measurement_scripts(ROOT) == []


def test_the_layout_check_names_a_misplaced_measurement_script(tmp_path: Path) -> None:
    (tmp_path / "adapters.json").write_text('{"adapters": {"a": "adapters/a/adapter.json"}}', encoding="utf-8")
    script = 'if __name__ == "__main__":\n    main()\n'
    for folder in ("test/measure", "adapters/a/test/browser", "adapters/a/test/measure"):
        (tmp_path / folder).mkdir(parents=True)
    (tmp_path / "test" / "measure" / "cost.py").write_text(script, encoding="utf-8")
    (tmp_path / "adapters" / "a" / "test" / "measure" / "timing.py").write_text(script, encoding="utf-8")
    (tmp_path / "adapters" / "a" / "test" / "browser" / "speed.py").write_text(script, encoding="utf-8")
    (tmp_path / "adapters" / "a" / "test" / "helper.py").write_text(script, encoding="utf-8")
    (tmp_path / "adapters" / "a" / "test" / "test_helper.py").write_text("import helper\n", encoding="utf-8")

    found = misplaced_measurement_scripts(tmp_path)

    assert len(found) == 1
    assert found[0].startswith("adapters/a/test/browser/speed.py:")
    assert "adapters/a/test/measure/" in found[0]
    assert "architecture.md#repository-layout" in found[0]
