"""obs's spec references the HTML adapter's specification as an outside source.

Owner: spec/appendix/references/obs-html-specification.md, whose silent cmd fences (producers,
capabilities/command-fences) build adapters/html/spec/manifest.md with the adapter into the file
the note attaches (capabilities/attachments). The References register selects every note with a
`url` (spec/appendix/references.md).
"""
import base64
import re

NOTE = "appendix/references/obs-html-specification.md"


def _nodes(nodes):
    for node in nodes:
        yield node
        yield from _nodes(node.get("children", []))


def _chapters(chapters):
    for chapter in chapters:
        yield chapter
        yield from _chapters(chapter.get("children", []))


def test_the_references_entry_attaches_the_built_html_specification(spec_document) -> None:
    [record] = [record for record in spec_document["records"] if record.get("path") == NOTE]
    assert record["fields"]["url"].endswith("/adapters/html/spec/manifest.md")
    # The register's filter is `url != null`; an adapter evaluates it on the records
    # (capabilities/bases, Document node), so a non-ignored record with a url is its entry.
    [references] = [chapter for chapter in _chapters(spec_document["chapters"])
                    if chapter["id"] == "appendix-references"]
    [register] = [node for node in _nodes(references["content"]) if node["type"] == "bases"]
    assert register["attrs"]["spec"]["filters"] == "url != null"
    assert not record.get("ignored"), f"{NOTE}: an ignored note is no entry of the References register"

    [chapter] = [chapter for chapter in spec_document["chapters"]
                 if chapter["id"] == "appendix-references-obs-html-specification"]
    [attachment] = [node for node in _nodes(chapter["content"]) if node["type"] == "attachments"]
    [asset] = [asset for asset in spec_document["assets"] if asset["id"] == attachment["attrs"]["asset"]]
    assert asset["path"] == "design_output/obs-html-specification.html"
    assert asset["mediaType"] == "text/html"

    html = base64.b64decode(asset["data"]).decode("utf-8")
    assert html.startswith("<!doctype html>")
    assert re.search(r"<title>obs-html</title>", html), (
        f"{NOTE}: the attached file is not the HTML adapter's specification (title obs-html)")
