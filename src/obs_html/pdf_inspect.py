"""obs-html-inspect: inspect a PDF without a viewer, so print output can be verified automatically."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

import pypdfium2 as pdfium

PROG = "obs-html-inspect"

EPILOG = """Pages are numbered from 1. Coordinates are PDF points (1/72 inch) from the top-left
corner of the page, x to the right and y down; a raster pixel at --scale S is S points wide.

Examples:
  obs-html-inspect render document.pdf --page 1 --output page-1.png
  obs-html-inspect crop document.pdf --page 1 --box 72,72,300,200 --output title.png
  obs-html-inspect text document.pdf --page 2
"""


class InspectError(RuntimeError):
    """An inspection that cannot run; the message names the input and the remedy."""


def _open_page(pdf: Path, number: int) -> pdfium.PdfPage:
    try:
        document = pdfium.PdfDocument(pdf)
    except pdfium.PdfiumError as error:
        raise InspectError(f"cannot read {pdf} as a PDF ({error}). Remedy: pass a PDF file.") from error
    if not 1 <= number <= len(document):
        raise InspectError(f"{pdf} has {len(document)} pages, no page {number}. "
                           f"Remedy: pass --page from 1 to {len(document)}.")
    return document[number - 1]


def render_page(pdf: Path, number: int, scale: float, output: Path) -> tuple[int, int]:
    """Write page NUMBER of PDF as a raster at SCALE pixels per point; return its size."""
    image = _open_page(pdf, number).render(scale=scale).to_pil()
    image.save(output)
    return image.size


Box = tuple[float, float, float, float]


def parse_box(text: str, option: str) -> Box:
    """X0,Y0,X1,Y1 as four numbers with X0 < X1 and Y0 < Y1."""
    try:
        x0, y0, x1, y1 = (float(part) for part in text.split(","))
    except ValueError:
        raise InspectError(f"{option} {text!r}: expected X0,Y0,X1,Y1. "
                           f"Remedy: pass four comma-separated numbers, for example 72,72,300,200.") from None
    if not (x0 < x1 and y0 < y1):
        raise InspectError(f"{option} {text}: the box is empty. Remedy: pass X0 < X1 and Y0 < Y1.")
    return x0, y0, x1, y1


def crop_page(pdf: Path, number: int, box: Box, scale: float, output: Path) -> tuple[int, int]:
    """Write the BOX region of page NUMBER as a raster, rendered at SCALE; return its size."""
    page = _open_page(pdf, number)
    width, height = page.get_size()
    x0, y0, x1, y1 = box
    if x0 < 0 or y0 < 0 or x1 > width or y1 > height:
        raise InspectError(f"--box {_number_list(box)} is not inside the page (0,0,{width:g},{height:g} pt). "
                           f"Remedy: pass a box within the page.")
    image = page.render(scale=scale, crop=(x0, height - y1, width - x1, y0)).to_pil()
    image.save(output)
    return image.size


def page_text(pdf: Path, number: int) -> str:
    """The text of page NUMBER in the order pdfium reads it, with \\n line breaks."""
    text = _open_page(pdf, number).get_textpage().get_text_range()
    return "\n".join(text.replace("\r\n", "\n").replace("\r", "\n").splitlines()) + "\n"


def _number_list(values: Sequence[float]) -> str:
    return ",".join(f"{value:g}" for value in values)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG, description="Inspect a PDF without a viewer.", epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    render = commands.add_parser("render", help="Render a page to a raster image.")
    render.add_argument("pdf", type=Path, metavar="PDF", help="PDF to read.")
    render.add_argument("--page", type=int, required=True, help="Page number, from 1.")
    render.add_argument("--scale", type=float, default=2.0,
                        help="Pixels per PDF point (default 2, which is 144 dpi).")
    render.add_argument("--output", type=Path, required=True, metavar="IMAGE",
                        help="Raster written, for example page.png.")
    crop = commands.add_parser("crop", help="Render a region of a page to a raster image.")
    crop.add_argument("pdf", type=Path, metavar="PDF", help="PDF to read.")
    crop.add_argument("--page", type=int, required=True, help="Page number, from 1.")
    crop.add_argument("--box", required=True, metavar="X0,Y0,X1,Y1", help="Region in points.")
    crop.add_argument("--scale", type=float, default=2.0, help="Pixels per PDF point (default 2).")
    crop.add_argument("--output", type=Path, required=True, metavar="IMAGE", help="Raster written.")
    text = commands.add_parser("text", help="Extract the text of a page.")
    text.add_argument("pdf", type=Path, metavar="PDF", help="PDF to read.")
    text.add_argument("--page", type=int, required=True, help="Page number, from 1.")
    text.add_argument("--output", type=Path, metavar="TEXT",
                      help="UTF-8 text file written; without it the text goes to stdout.")
    return parser


def _deliver_text(content: str, output: Path | None, what: str) -> None:
    """Print CONTENT, or write it to the named OUTPUT file and say so."""
    if output is None:
        sys.stdout.write(content)
        return
    output.write_text(content, encoding="utf-8")
    print(f"Wrote {output} ({what}).")


def main(argv: Sequence[str] | None = None) -> None:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "render":
            width, height = render_page(arguments.pdf, arguments.page, arguments.scale, arguments.output)
            print(f"Wrote {arguments.output} ({width}x{height} px, page {arguments.page}, "
                  f"scale {arguments.scale:g}).")
        elif arguments.command == "crop":
            box = parse_box(arguments.box, "--box")
            width, height = crop_page(arguments.pdf, arguments.page, box, arguments.scale, arguments.output)
            print(f"Wrote {arguments.output} ({width}x{height} px, page {arguments.page}, "
                  f"box {_number_list(box)} pt, scale {arguments.scale:g}).")
        elif arguments.command == "text":
            _deliver_text(page_text(arguments.pdf, arguments.page), arguments.output,
                          f"page {arguments.page} text")
    except InspectError as error:
        print(f"{PROG} {arguments.command}: {error}", file=sys.stderr)
        raise SystemExit(2) from None
