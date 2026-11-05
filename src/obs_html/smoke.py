"""Render the minimum HTML document supported by the adapter contract."""
import argparse
import html
import json
from pathlib import Path
from typing import Sequence


def render(document_path: Path, destination: Path) -> None:
    document = json.loads(document_path.read_text(encoding="utf-8"))
    title = html.escape(document["manifest"]["title"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        "<!doctype html>\n"
        f"<html lang=\"en\"><head><meta charset=\"utf-8\"><title>{title}</title></head>"
        f"<body><h1>{title}</h1></body></html>\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a smoke-test HTML document.")
    parser.add_argument("document", type=Path)
    parser.add_argument("destination", type=Path)
    options = parser.parse_args(argv)
    render(options.document, options.destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
