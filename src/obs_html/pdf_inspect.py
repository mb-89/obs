"""obs-html-inspect: inspect a PDF without a viewer, so print output can be verified automatically."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

import pypdfium2 as pdfium

PROG = "obs-html-inspect"

EPILOG = """Pages are numbered from 1.

Examples:
  obs-html-inspect render document.pdf --page 1 --output page-1.png
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
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "render":
            width, height = render_page(arguments.pdf, arguments.page, arguments.scale, arguments.output)
            print(f"Wrote {arguments.output} ({width}x{height} px, page {arguments.page}, "
                  f"scale {arguments.scale:g}).")
    except InspectError as error:
        print(f"{PROG} {arguments.command}: {error}", file=sys.stderr)
        raise SystemExit(2) from None
