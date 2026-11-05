"""The PDF inspection tools, run on the fixture Document's printed PDF."""
import base64
from pathlib import Path

import pytest
from PIL import Image

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
