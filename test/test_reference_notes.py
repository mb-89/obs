"""Every external link goes through a note (input-model.md "Reference notes and link text")."""
import re
from pathlib import Path

from obs_html.cli import main
from obs_html.content import compile_base_filter
from obs_html.artifact_data import decode_artifact_data

URL = "https://webstore.iec.ch/publication/1234"
# The references register is an authored Bases view (input-model.md "Registers"), not a macro.
REGISTER = ("```base\nfilters: 'url != null'\nproperties:\n  title: {displayName: Reference}\n"
            "  description: {displayName: Description}\nviews:\n  - type: table\n    name: References\n"
            "    order: [title, description]\n```\n")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build(vault: Path, capsys=None) -> tuple[dict, str]:
    output = vault.parent / f"{vault.name}.html"
    assert main(["--source", str(vault), "--output", str(output)]) == 0
    errors = capsys.readouterr().err if capsys else ""
    return decode_artifact_data(output.read_text(encoding="utf-8")), errors


def reference_vault(root: Path) -> Path:
    vault = root / "vault"
    write(vault / "manifest.md", "- [[one]]\n- [[registers]]\n")
    write(vault / "one.md", "# One\n\nThe limit follows [[iec]]. See also [the standard](nodes/iec.md) "
          "and [[iec|IEC 1234]]. The gap is [[q_gap]]; the frame is [[frame]].\n")
    write(vault / "registers.md", "---\ntitle: Registers\n---\n" + REGISTER)
    write(vault / "nodes/iec.md", f"---\ntitle: IEC 1234\nurl: {URL}\n"
          "description: Safety of medical electrical equipment.\naccessed: 2026-10-29\n---\n")
    write(vault / "nodes/catalog-item.md", "---\ntitle: REQ-7\nkind: item\n"
          "url: https://catalog.example/items/7\n---\n")
    write(vault / "nodes/no-url.md", "---\nkind: reference\ndocument: Drawing\n---\n")
    write(vault / "nodes/q_gap.md", "---\nkind: quantity\ntitle: Gap\naliases: [q_gap]\n"
          "value: 2.0\nunit: mm\nsource: '[[iec]]'\n---\n")
    write(vault / "nodes/frame.md", "---\ntitle: Frame drawing\n---\nThe frame.\n")
    return vault


def test_one_url_linked_three_times_is_one_note_and_three_internal_links(tmp_path, capsys) -> None:
    data, errors = build(reference_vault(tmp_path), capsys)
    notes = {note["slug"]: note for note in data["notes"]}
    html = notes["one"]["html"]
    assert html.count('href="#nodes-iec"') == 3
    assert "https://" not in html
    holders = [note for note in data["notes"] if note["frontmatter"].get("url") == URL]
    assert [note["slug"] for note in holders] == ["nodes-iec"]
    assert "Warning" not in errors


def test_unlabelled_links_render_by_target_kind(tmp_path) -> None:
    data, _ = build(reference_vault(tmp_path))
    html = {note["slug"]: note for note in data["notes"]}["one"]["html"]
    assert '<a href="#nodes-q-gap">2 mm</a>' in html
    assert '<a href="#nodes-frame">Frame drawing</a>' in html
    assert '<a href="#nodes-iec">IEC 1234</a>' in html
    assert '<a href="#nodes-iec">the standard</a>' in html


def test_references_register_is_a_query_over_notes_with_a_url(tmp_path) -> None:
    selects = compile_base_filter("url != null")
    assert selects({"url": URL}.get) and selects({"url": "https://catalog.example/items/7", "kind": "item"}.get)
    assert not selects({"kind": "reference", "document": "Drawing"}.get)
    data, _ = build(reference_vault(tmp_path))
    register = {note["slug"]: note for note in data["notes"]}["registers"]["tables"]
    assert [table["definition"]["filters"] for table in register] == ["url != null"]
    slugs = {note["slug"] for note in data["notes"]}
    # The query includes every note with a URL, whatever its kind; a reference note without a URL
    # is not a register row and stays out.
    assert {"nodes-iec", "nodes-catalog-item"} <= slugs
    assert "nodes-no-url" not in slugs


def test_direct_external_links_are_lint_warnings(tmp_path, capsys) -> None:
    vault = tmp_path / "vault"
    write(vault / "manifest.md", "- [[one]]\n")
    write(vault / "one.md", "# One\n\nRead https://example.org/bare now, [a link](https://example.org/md)"
          " and <https://example.org/auto>. Code `https://example.org/code` is literal.\n\n"
          "```base\nfilters: 'kind == \"item\"'\nproperties:\n  id:\n    obsHtml: {linkProperty: url}\n"
          "views:\n  - {type: table, order: [id]}\n```\n")
    write(vault / "item.md", "---\nkind: item\nid: A-1\nurl: https://catalog.example/items/1\n---\n")
    _, errors = build(vault, capsys)
    warnings = [line for line in errors.splitlines() if line.startswith("Warning:")]
    assert [re.search(r"external link (\S+) in prose", line)[1] for line in warnings[:3]] == [
        "https://example.org/bare", "https://example.org/md", "https://example.org/auto"]
    assert len(warnings) == 4
    assert "one.md:3:" in warnings[0]
    assert "properties.id.obsHtml.linkProperty url resolves to an external URL" in warnings[3]
