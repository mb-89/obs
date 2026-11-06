"""The figure lint runs in the core: a figure without a caption, a caption outside its figure and
a typed figure number are source-located warnings in the Document's diagnostics, which every
build prints (input-model, Figure captions and references).

Reader: whoever changes the figure lint.
"""
from pathlib import Path

from obs.document import build_document

from test_vault import capability_reference


SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"/>'
OWNER = "see input-model#Figure captions and references"


def figure(name: str | None = "a", caption: str | None = "A figure.") -> str:
    lines = ["```figure", "version: 1", "kind: image", "source: img.svg"]
    lines += [f"caption: {caption}"] if caption else []
    return "\n".join([*lines, "```", *([f"^{name}"] if name else [])]) + "\n\n"


def warnings(tmp_path: Path, body: str) -> list[str]:
    (tmp_path / "img.svg").write_text(SVG, encoding="utf-8")
    (tmp_path / "notes.pdf").write_bytes(b"%PDF-1.4\n")
    (tmp_path / "manifest.md").write_text("- [[one]]\n", encoding="utf-8")
    (tmp_path / "one.md").write_text("---\ntitle: One\n---\n# One\n\n" + body, encoding="utf-8")
    document = build_document(tmp_path / "manifest.md", capability_reference())
    return [diagnostic["message"] for diagnostic in document["diagnostics"]]


def test_a_captioned_figure_with_a_block_link_has_no_warnings(tmp_path) -> None:
    assert warnings(tmp_path, figure() + "See [[#^a]].\n") == []


def test_a_figure_without_caption_and_a_lone_image_warn_at_their_line(tmp_path) -> None:
    found = warnings(tmp_path, figure(caption=None) + "![Drawing](img.svg)\n\n![Attachment](notes.pdf)\n")

    assert [message.split(": ", 1)[0] for message in found] == ["one.md:6", "one.md:13"]
    assert all(message.endswith(f"{OWNER}.") for message in found)
    assert "kind: image, source: img.svg" in found[1]


def test_a_caption_outside_the_figure_warns_once(tmp_path) -> None:
    found = warnings(tmp_path, "*The drawing.*\n\n" + figure() + "Figure 1: the drawing.\n\nProse after.\n")

    assert [message.split(": ", 1)[0] for message in found] == ["one.md:6", "one.md:16"]
    assert all(message.endswith(f"{OWNER}.") for message in found)


def test_a_typed_figure_number_suggests_the_block_link_of_the_figure_at_that_position(tmp_path) -> None:
    found = warnings(tmp_path, figure("a") + figure("b") + figure(None) + "As Fig. 2 and Abb. 1.3 show, "
                     "see `Figure 4`.\n\n" + figure("c", "Unlike Figure 9."))

    assert [message.split(": ", 1)[0] for message in found] == ["one.md:29", "one.md:29", "one.md:31"]
    assert "[[#^b]]" in found[0]
    assert "line 22" in found[1]  # The third figure has no block id: the suggestion adds one.
    assert "[[#^" in found[2]
    assert all(message.endswith(f"{OWNER}.") for message in found)


def test_every_build_prints_the_warnings(tmp_path, capsys) -> None:
    from obs.document import main

    (tmp_path / "img.svg").write_text(SVG, encoding="utf-8")
    (tmp_path / "manifest.md").write_text("- [[one]]\n", encoding="utf-8")
    (tmp_path / "one.md").write_text("# One\n\n" + figure(caption=None), encoding="utf-8")
    assert main(["--source", str(tmp_path / "manifest.md"), "--document", str(tmp_path / "out.json")]) == 0

    assert "one.md:3: " in capsys.readouterr().err
