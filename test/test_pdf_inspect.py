"""The PDF inspection tools, run on the fixture Document's printed PDF."""
import base64
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from conftest import FIXTURE
from obs_html import cli, pdf_inspect


PIXEL = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
LETTER = (612, 792)  # The fixture's paper, in PDF points.


@pytest.fixture(scope="module")
def printed(tmp_path_factory) -> Path:
    """The fixture Document printed once by this repository's own PDF path."""
    folder = tmp_path_factory.mktemp("printed")
    (folder / "images").mkdir()
    (folder / "images" / "logo.png").write_bytes(base64.b64decode(PIXEL))
    pdf = folder / "document.pdf"
    cli.main([str(FIXTURE), str(pdf), "--execute-commands", "--command-root", str(folder)])
    return pdf


def test_render_writes_the_page_as_a_raster_at_the_scale(printed, tmp_path, capsys) -> None:
    output = tmp_path / "page.png"
    pdf_inspect.main(["render", str(printed), "--page", "1", "--scale", "1.5", "--output", str(output)])
    with Image.open(output) as image:
        assert image.size == (918, 1188)
        darkest, lightest = image.convert("L").getextrema()
        assert darkest < lightest  # Printed content, not a blank page.
    assert f"Wrote {output} (918x1188 px, page 1, scale 1.5)." in capsys.readouterr().out


def test_render_names_the_pages_a_pdf_has(printed, tmp_path, capsys) -> None:
    with pytest.raises(SystemExit) as exit_info:
        pdf_inspect.main(["render", str(printed), "--page", "99", "--output", str(tmp_path / "x.png")])
    assert exit_info.value.code == 2
    error = capsys.readouterr().err
    assert error.startswith(f"obs-html-inspect render: {printed} has ") and "Remedy: pass --page from 1 to" in error


def test_crop_renders_a_region_in_points_from_the_top_left(printed, tmp_path, capsys) -> None:
    page, region = tmp_path / "page.png", tmp_path / "region.png"
    pdf_inspect.main(["render", str(printed), "--page", "1", "--scale", "2", "--output", str(page)])
    pdf_inspect.main(["crop", str(printed), "--page", "1", "--box", "100,50,300,250",
                      "--scale", "2", "--output", str(region)])
    with Image.open(page) as whole, Image.open(region) as part:
        assert part.size == (400, 400)
        aligned = whole.convert("L").crop((200, 100, 600, 500))
        shifted = whole.convert("L").crop((204, 104, 604, 504))
        assert _mean_difference(aligned, part) < 0.5 < _mean_difference(shifted, part)
    assert f"Wrote {region} (400x400 px, page 1, box 100,50,300,250 pt, scale 2)." in capsys.readouterr().out


def _mean_difference(first: Image.Image, second: Image.Image) -> float:
    """Mean grey difference in 0-255; anti-aliasing differs slightly between renders."""
    histogram = ImageChops.difference(first.convert("L"), second.convert("L")).histogram()
    return sum(level * count for level, count in enumerate(histogram)) / sum(histogram)


@pytest.mark.parametrize("box, problem", [
    ("1,2,3", "expected X0,Y0,X1,Y1"),
    ("300,50,100,250", "X0 < X1 and Y0 < Y1"),
    ("0,0,700,100", "inside the page (0,0,612,792 pt)"),
])
def test_crop_refuses_a_box_it_cannot_cut(printed, tmp_path, capsys, box, problem) -> None:
    with pytest.raises(SystemExit):
        pdf_inspect.main(["crop", str(printed), "--page", "1", "--box", box, "--output", str(tmp_path / "x.png")])
    error = capsys.readouterr().err
    assert "obs-html-inspect crop: --box" in error and problem in error and "Remedy:" in error
    assert not (tmp_path / "x.png").exists()


def test_text_prints_the_page_text_in_reading_order(printed, capsys) -> None:
    pdf_inspect.main(["text", str(printed), "--page", "1"])
    lines = capsys.readouterr().out.splitlines()
    assert lines.index("Fixture document") < lines.index("Authors") < lines.index("Ada, Lin")
    assert not any("\r" in line for line in lines)


def test_text_writes_the_named_file(printed, tmp_path, capsys) -> None:
    output = tmp_path / "page-1.txt"
    pdf_inspect.main(["text", str(printed), "--page", "1", "--output", str(output)])
    assert "Fixture document\n" in output.read_text(encoding="utf-8")
    assert capsys.readouterr().out == f"Wrote {output} (page 1 text).\n"
